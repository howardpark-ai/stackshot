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
  * config.notes says an entry of gmail_names the reader skips, two names that differ only in case (in either order), and two names for one address; RESTART_ONLY holds gmail_names.
  * the query grammar through the reader and the tool (the grammar itself is tests/gmail_query_grammar_scenario.py): an OR, an AND and a `key:(a OR b)` anchor hears the mail it
    should; an unsupported query is refused when added with one line naming what is wrong and nothing is stored, a stored one can still be removed, and the add reply shows how
    the query is read; the wait gate refuses such a query too.
  * a scope is a set: the same mailboxes in another order are one anchor (add and remove, also against a hand-made stored order); a #mention variant stays its own anchor; a scope with an
    unknown name keeps its spelling; labels that differ only in case are told apart by their exact spelling; a hand-made empty scope is shown and reported as reading nothing.
  * the reader pages Gmail's history: a fake Google answers with nextPageToken, every page's mail is heard, the page size and the cap hold, and a poll that stops at the cap goes on
    from the last record it read; only Google's 404 status (never '404' in an error's text) resyncs an expired history; a mailbox no query anchor reads costs no messages.get; a poll makes at
    most MESSAGE_GETS gets and goes on from the last record it handled whole; a repeated record (an inclusive startHistoryId) delivers nothing twice.
  * the label rules of the reader (gmail_names entries with a bad name or address are skipped, labels are listed in name order); the add reply's wording; a removal on a project whose page is gone.

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
OR1, OR2, OR3 = "gmail:q:from:(zed OR pat)", "gmail:q@home:from:zed OR subject:quarterly", "gmail:q:from:zed OR from:amy"      # the grammar: OR, a key group, no match
AND1, GRP = "gmail:q@work:from:pat AND subject:quarterly", "gmail:q:(from:zed OR from:pat) AND (subject:budget OR subject:numbers)"
STOREDBAD = "gmail:q:subject:quarterly(x"      # stored before the grammar, which refuses it: the old matcher reads it, and it matches nothing here
h = core.Hub(); h.status["receivers"] = {}; h.triggers = FastQ()
h.bindings = {a: {"sess"} for a in (UN, W, H, WH, GONE, WGONE, OTHER, EMPTY, AT, AT2, OR1, OR2, OR3, AND1, GRP, STOREDBAD)}
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
check("reader: an OR in a key group hears the mail in every mailbox it reads", heard(OR1) == [ADA, BO], events)
check("reader: an OR of a term that does not match and one that does, in a scope", heard(OR2) == [BO], events)
check("reader: an OR with no matching side hears nothing", heard(OR3) == [], events)
check("reader: AND in a scope", heard(AND1) == [ADA], events)
check("reader: groups joined by AND", heard(GRP) == [ADA, BO], events)
check("reader: a stored query the grammar refuses is read as it always was (here: no match) and does not stop the reader", heard(STOREDBAD) == [] and heard(W) == [ADA], events)
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

# ---- the query grammar through the tool: a query the matcher cannot evaluate is refused when added (one line, nothing stored); one that works is shown as it is read
from stackshot.anchors import gmail_query as gq
pathlib.Path(core.STATUS).write_text(saved_status)
(T / "store/anchors.json").write_text("{}")
REFUSALS = [("gmail:q:from:pat AND", "AND has nothing after it"), ("gmail:q:OR from:pat", "OR has nothing before it"),
            ("gmail:q:(from:pat OR from:amy", "an opening parenthesis is never closed"), ("gmail:q@work:(from:pat", "an opening parenthesis is never closed"),
            ("gmail:q:label:x", "label: is not supported"), ("gmail:q:-from:pat", "negation (-from) is not supported"), ("gmail:q:from:()", "has nothing inside"),
            ("gmail:q@home,work:from:pat AND (", "has nothing inside"), ("gmail:q:(from:pat#mention=sam", "never closed"),
            ("gmail:q:from:pat AND#mention=sam", "AND has nothing after it"), (STOREDBAD, "")]      # the #mention fragment is no part of the query: the query before it is the one judged
for url, why in REFUSALS:
    try: anchors(add=[url]); check(f"tool grammar: {url!r} is refused when added", False, stored())
    except Exception as e:
        m = str(e)
        check(f"tool grammar: {url!r} is refused with one line naming what is wrong", m.startswith("Refused: the Gmail query in") and "is not one the matcher can evaluate: " in m and why in m and "\n" not in m, m)
        check(f"tool grammar: {url!r}: the reason is the matcher's own", gq.problem(anc.gmail_query(anc.split_fragment(url)[0])[1]) in m, m)
check("tool grammar: no refused add stored anything", stored() == [], stored())
check("tool grammar: the refusal names the terms a query may use", all(s in m for s in ("from:, to:, cc:, subject: and person:", "AND, OR and parentheses", "key:(a OR b)", "quotation marks")), m)
out = anchors(add=["gmail:q@work:from:pat AND subject:quarterly"])
check("tool grammar: an AND query in a scope is stored and the reply shows how it is read", stored() == ["gmail:q@work:from:pat AND subject:quarterly"]
      and 'It matches a mail when: from contains "pat" AND subject contains "quarterly".' in out, out)
check("tool reply: a scoped query names its mailboxes with no remark about every mailbox", "Gmail query 'from:pat AND subject:quarterly' reads the mailboxes: work." in out, out)
out = anchors(add=["gmail:q:from:(zed OR pat)"])
check("tool grammar: a key group is stored and shown as the OR of its keys", "gmail:q:from:(zed OR pat)" in stored() and 'It matches a mail when: from contains "zed" OR from contains "pat".' in out, out)
check("tool reply: an unscoped query names every mailbox, and says the other form reads one",
      "Gmail query 'from:(zed OR pat)' reads the mailboxes: home, work (every mailbox the anchors service reads; gmail:q@<mailbox>:<query> reads only the one named)." in out, out)
tail = out.split("\nThe anchors service reads each new anchor", 1)
check("tool reply: the closing text speaks of the anchors service, with no component name, and says a Gmail query is named at once",
      len(tail) == 2 and "within two minutes" in tail[1] and "hub" not in tail[1].lower() and "other than a Gmail query (named by its mailboxes at once)" in tail[1], out)
out = anchors(add=["gmail:q:from:pat subject:quarterly"])
check("tool grammar: an old query is stored as typed and read as it always was", "gmail:q:from:pat subject:quarterly" in stored() and 'It matches a mail when: from contains "pat" AND subject contains "quarterly".' in out, out)
os.remove(core.STATUS)
out = anchors(add=["gmail:q:from:pat OR from:amy"])
check("tool reply: with no mailbox known the reply says so (M35)", "reads the mailboxes: none the anchors service has named yet (every mailbox" in out and 'from contains "pat" OR from contains "amy"' in out, out)
pathlib.Path(core.STATUS).write_text(saved_status)
# a query stored before the grammar can still be listed and removed
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": STOREDBAD, "items": None, "added": 1, "by": "t"}]}))
check("tool grammar: a stored query the grammar refuses is listed", "subject:quarterly(x" in anchors(), stored())
anchors(remove=[STOREDBAD])
check("tool grammar: …and removed", stored() == [], stored())
# the wait gate
gate = lambda url: server._anchor_wait_gate({}, {"wait_kind": "anchor", "wait_anchor": url, "project": "projects/alpha"}, creating=True)
refuse("wait gate: a query the matcher cannot evaluate is refused with the reason", lambda: gate("gmail:q:from:pat AND"), "cannot evaluate", "AND has nothing after it", "can never be on the list")
refuse("wait gate: a good query that is not on the list still gets the add-first refusal", lambda: gate("gmail:q:from:pat OR from:amy"), "is not on projects/alpha's anchors list")
check("tool text: the description teaches the grammar and the refusal", all(s in server._ANCHORS_DESC for s in ("AND", "OR", "key:(a OR b)", "in capitals", "no negation", "is refused when added")), server._ANCHORS_DESC[:200])

# ---- a scope is a set: the same mailboxes in another order are one anchor
(T / "store/anchors.json").write_text("{}")
anchors(add=["gmail:q@work,home:from:pat"]); anchors(add=["gmail:q@home,work:from:pat"]); anchors(add=["gmail:q@WORK,Home:from:pat"])
check("set scope: the mailboxes in any order are one anchor, stored in label order", stored() == ["gmail:q@home,work:from:pat"], stored())
anchors(remove=["gmail:q@work,home:from:pat"])
check("set scope: a removal in the other order finds it", stored() == [], stored())
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": "gmail:q@work,home:from:pat", "items": None, "added": 1, "by": "t"}]}))      # a hand-made order
anchors(add=["gmail:q@home,work:from:pat"])
check("set scope: an anchor stored in the other order is the one added to (no second entry)", stored() == ["gmail:q@work,home:from:pat"], stored())
anchors(add=["gmail:q@home,work:from:pat#mention=sam"])
check("set scope: a #mention variant is its own anchor (M31)", sorted(stored()) == ["gmail:q@home,work:from:pat#mention=sam", "gmail:q@work,home:from:pat"], stored())
anchors(remove=["gmail:q@home,work:from:pat"])
check("set scope: a removal takes the stored spelling and leaves the #mention variant", stored() == ["gmail:q@home,work:from:pat#mention=sam"], stored())
anchors(remove=["gmail:q@work,home:from:pat#mention=sam"])
check("set scope: …and the variant goes in the other order too", stored() == [], stored())
check("set scope: gmail_canonical sorts the labels and keeps a scope with an unknown name as written (M12)",
      anc.gmail_canonical("gmail:q@work,home:x", BX) == "gmail:q@home,work:x" and anc.gmail_canonical("gmail:q@work,nope:x", BX) == "gmail:q@work,nope:x"
      and anc.gmail_canonical("gmail:q:x", BX) == "gmail:q:x" and anc.gmail_canonical("gmail:q@:x", BX) == "gmail:q@:x" and anc.gmail_canonical("gmail:1111111111111111", BX) == "gmail:1111111111111111",
      (anc.gmail_canonical("gmail:q@work,nope:x", BX), anc.gmail_canonical("gmail:q@:x", BX)))
# a hand-made empty scope
check("empty scope: the title says no mailbox is named, never the plain anchor", anc.gmail_title(EMPTY, BX) == "from:pat · no mailbox named", anc.gmail_title(EMPTY, BX))
re_ = res(EMPTY)
check("empty scope: the reader reports it unreadable, saying why", re_.get("title") == "from:pat · no mailbox named" and "names no mailbox" in re_.get("unreadable", ""), re_)
(T / "store/anchors.json").write_text(json.dumps({"projects/alpha": [{"url": EMPTY, "items": None, "added": 1, "by": "t"}]}))
check("empty scope: the tool list shows it as naming no mailbox", "no mailbox named" in anchors(), anchors())
(T / "store/anchors.json").write_text("{}")
# labels that differ only in case
for order in (({"Work": ADA, "work": BO}), ({"work": BO, "Work": ADA})):
    CB = dict(order)
    check("case labels: the exact spelling picks its mailbox, another case picks the label that sorts first", anc.gmail_resolve(["work"], CB) == (["work"], []) and anc.gmail_resolve(["Work"], CB) == (["Work"], [])
          and anc.gmail_resolve(["WORK"], CB) == (["Work"], []) and anc.gmail_resolve([ADA], CB) == (["Work"], []), (order, anc.gmail_resolve(["WORK"], CB)))
    check("case labels: a scope reads the mailbox its exact spelling names",
          anc.gmail_reads("gmail:q@work:x", BO, CB) and not anc.gmail_reads("gmail:q@work:x", ADA, CB) and anc.gmail_reads("gmail:q@Work:x", ADA, CB) and not anc.gmail_reads("gmail:q@Work:x", BO, CB)
          and anc.gmail_reads("gmail:q@WORK:x", ADA, CB) and not anc.gmail_reads("gmail:q@WORK:x", BO, CB), order)
    check("case labels: both spellings in one scope read both, written in label order", anc.gmail_canonical("gmail:q@work,Work:x", CB) == "gmail:q@Work,work:x" and anc.gmail_title("gmail:q@work,Work:x", CB) == "x · work, Work", anc.gmail_title("gmail:q@work,Work:x", CB))
n1, n2 = nt({"Work": ADA, "work": BO}), nt({"work": BO, "Work": ADA})
check("case labels: the startup note is one line, the same in either order, and says which mailbox another case reads (M39)",
      len(n1) == 1 and n1 == n2 and "'Work' and 'work' differ only in case" in n1[0] and "any other case of them reads 'Work'" in n1[0], (n1, n2))
check("case labels: the note does not say the last one wins (it is not true of case)", "last one wins" not in n1[0], n1)
n3 = nt({"a": ADA, "b": ADA})
check("names: two names for one address say the last one wins, and the reader does let it", len(n3) == 1 and "the last one wins" in n3[0], n3)
_names = core._cfg.CFG["anchor_hub"]["gmail_names"]
try:
    core._cfg.CFG["anchor_hub"]["gmail_names"] = {"a": ADA, "b": ADA}
    check("names: the reader gave the address its last name", gw.mailbox_labels([ADA]) == {"b": ADA}, gw.mailbox_labels([ADA]))
    core._cfg.CFG["anchor_hub"]["gmail_names"] = {"work": ADA, "my work": BO, "bad": "not-an-address", "home": BO, "x@y": CY}
    check("labels: an entry with a bad name or a bad address is skipped, the others name their mailbox (M17)", gw.mailbox_labels([ADA, BO, CY]) == {CY: CY, "home": BO, "work": ADA}, gw.mailbox_labels([ADA, BO, CY]))
    core._cfg.CFG["anchor_hub"]["gmail_names"] = {"bad": "not-an-address"}
    check("labels: an address that is no address names nothing, and the mailbox keeps its own address", gw.mailbox_labels([ADA]) == {ADA: ADA}, gw.mailbox_labels([ADA]))
    core._cfg.CFG["anchor_hub"]["gmail_names"] = {"w": "not an address"}
    check("labels: a name given to something that is no address is not used even for an account file of that name", gw.mailbox_labels(["not an address"]) == {"not an address": "not an address"}, gw.mailbox_labels(["not an address"]))
    core._cfg.CFG["anchor_hub"]["gmail_names"] = {"work": ADA, "home": BO}
    check("labels: the mailboxes are listed in name order, whichever order they are given (M19)", list(gw.mailbox_labels([CY, BO, ADA])) == [CY, "home", "work"] and list(gw.mailbox_labels([ADA, BO, CY])) == [CY, "home", "work"], list(gw.mailbox_labels([CY, BO, ADA])))
finally:
    core._cfg.CFG["anchor_hub"]["gmail_names"] = _names
check("restart: gmail_names is read at start, so a changed value waits for a restart; the poll interval is live (M43)",
      _cfgmod._restart_only("anchor_hub.gmail_names") is not None and _cfgmod._restart_only("anchor_hub.gmail_poll_seconds") is None, (_cfgmod._restart_only("anchor_hub.gmail_names"), _cfgmod._restart_only("anchor_hub.gmail_poll_seconds")))
# the removal on a project whose page is gone takes the same spellings as the removal on a page
(T / "store/anchors.json").write_text(json.dumps({"projects/gone": [{"url": "gmail:q@home,work:from:pat", "items": None, "added": 1, "by": "t"}, {"url": "gmail:q@work:from:amy", "items": None, "added": 1, "by": "t"}]}))
txt = server._anchors("projects/gone", remove=["gmail:q@Work,HOME:from:pat"], who="tester")
left = [e["url"] for e in json.loads((T / "store/anchors.json").read_text()).get("projects/gone", [])]
check("gone page: a removal in another case and order finds the anchor, as on a page that exists", left == ["gmail:q@work:from:amy"] and "names no page any more" in txt, (left, txt))
refuse("gone page: nothing can be added to it", lambda: server._anchors("projects/gone", add=["gmail:q:from:pat"], who="tester"), "still holds anchors")
(T / "store/anchors.json").write_text("{}")

# ---- the reader pages Gmail's history
class Paged(Account):
    """A mailbox whose history is six records, "1".."6", one mail each, served `size` to a page with a nextPageToken; the history ids are numbers, as Gmail's are."""
    def __init__(self, email, size):
        super().__init__(email); self.size, self.calls, self.stop = size, [], (lambda: None)
        self.recs = [{"id": str(i), "messagesAdded": [{"message": {"id": f"m{i}", "threadId": f"t{i}"}}]} for i in range(1, 7)]
    def handle(self, key, kw):
        if key == "gmail.users.getProfile": return {"historyId": "0"}
        if key == "gmail.users.history.list":
            self.calls.append(dict(kw))
            todo = [r for r in self.recs if int(r["id"]) > int(kw["startHistoryId"])]
            at = int(kw.get("pageToken", 0)); more = at + self.size < len(todo)
            if not more or len(self.calls) > 12: self.stop()      # the last page ends the run (and so does a runaway)
            return {"history": todo[at:at + self.size], **({"nextPageToken": str(at + self.size)} if more else {}), "historyId": "99"}
        if key == "gmail.users.messages.get": return {**super().handle(key, kw), "snippet": kw["id"]}
        return super().handle(key, kw)
def run_paged(cap, size):
    """One mailbox with Paged history, polled with `cap` pages to a poll: → (the mail heard, the history.list calls, the cursor at the end, whether a further poll is queued)."""
    env0 = pathlib.Path(core.ENVF).read_text(); acct0, cap0, hl0 = accts[ADA], gw.HISTORY_PAGES, gw.HEALTH
    try:
        pathlib.Path(core.ENVF).write_text(f"GMAIL_ACCOUNTS={ADA}\n")
        pg = accts[ADA] = Paged(ADA, size); gw.HISTORY_PAGES = cap; gw.HEALTH = 10 ** 12
        hp = core.Hub(); hp.status["receivers"] = {}; hp.triggers = FastQ(); hp.bindings = {UN: {"sess"}}
        got = []; hp.event = lambda anchor, summ, kind="slack": got.append(summ["text"]); pg.stop = hp.stopping.set
        n = len(caught); gw.run(hp)
        lp = next(t for t in caught[n:] if t.__name__ == "loop")
        hp.triggers.put(("gmail", ADA)); lp()
        return got, pg.calls, hp.savers["google"]()[ADA]["hist"], not hp.triggers.empty()
    finally:
        pathlib.Path(core.ENVF).write_text(env0); accts[ADA], gw.HISTORY_PAGES, gw.HEALTH = acct0, cap0, hl0
        pathlib.Path(core.STATUS).write_text(saved_status)
got, calls, cur, more = run_paged(10, 2)
check("paging: every page of a busy mailbox's history is read in one poll, and its mail heard once", got == [f"m{i}" for i in range(1, 7)], got)
check("paging: the next page is asked for by the token the last one gave, and each call asks for the biggest page",
      [c.get("pageToken") for c in calls] == [None, "2", "4"] and all(c["startHistoryId"] == "0" and c["maxResults"] == gw.HISTORY_PAGE == 500 for c in calls), calls)
check("paging: the cursor ends at the history id Gmail reported, with no poll left queued", cur == "99" and not more, (cur, more))
got, calls, cur, more = run_paged(2, 2)
check("paging cap: a poll reads at most the cap's pages, and the rest is read on from where the poll stopped", [c["startHistoryId"] for c in calls] == ["0", "0", "4"] and [c.get("pageToken") for c in calls] == [None, "2", None], calls)
check("paging cap: no mail is lost or heard twice across the two polls", got == [f"m{i}" for i in range(1, 7)], got)
check("paging cap: the cursor ends at the history id Gmail reported", cur == "99", cur)
got, calls, cur, more = run_paged(2, 3)
check("paging cap: a history that ends on the last page the cap allows leaves no second poll", len(calls) == 2 and got == [f"m{i}" for i in range(1, 7)] and cur == "99" and not more, (calls, got, cur, more))

# ---- the reader tells an expired history from any other failure by the status, never by the text
def run_fake(make, bindings, total=None, saved=None, **consts):
    """One mailbox (ADA) served by the fake `make()` returns, polled until the fake calls its stop(); `consts` are gworkspace constants set for the run.
    `saved` is what a service that ran before left for this mailbox (its read position as hub.saved holds it); None: a first start.
    → (the (anchor, text) heard, the fake, the saved read position, whether a further poll is queued)."""
    env0 = pathlib.Path(core.ENVF).read_text(); acct0 = accts[ADA]; old = {k: getattr(gw, k) for k in ("HEALTH", *consts)}
    try:
        pathlib.Path(core.ENVF).write_text(f"GMAIL_ACCOUNTS={ADA}\n")
        pg = accts[ADA] = make(); gw.HEALTH = 10 ** 12
        for k, v in consts.items(): setattr(gw, k, v)
        hp = core.Hub(); hp.status["receivers"] = {}; hp.triggers = FastQ(); hp.bindings = {k: {"sess"} for k in bindings}
        if saved is not None: hp.saved = {"google": {ADA: saved}}
        got = []; pg.stop = hp.stopping.set
        def heard_(anchor, summ, kind="slack"):
            got.append((anchor, summ["text"]))
            if total is not None and len(got) >= total: hp.stopping.set()      # everything expected is heard: the pass in hand ends the run
        hp.event = heard_
        n = len(caught); gw.run(hp)
        lp = next(t for t in caught[n:] if t.__name__ == "loop")
        hp.triggers.put(("gmail", ADA)); lp()
        return got, pg, hp.savers["google"]()[ADA], not hp.triggers.empty()
    finally:
        pathlib.Path(core.ENVF).write_text(env0); accts[ADA] = acct0
        for k, v in old.items(): setattr(gw, k, v)
        pathlib.Path(core.STATUS).write_text(saved_status)
class HttpErr(Exception):
    """What googleapiclient raises: a message that spells out the request URL, and the status on .resp."""
    def __init__(self, status, text): super().__init__(text); self.resp = types.SimpleNamespace(status=status)
class Failing(Account):
    """history.list answers with one error; getProfile numbers its answers p1, p2, ... so a resync shows."""
    def __init__(self, email, status, text): super().__init__(email); self.status, self.text, self.profiles, self.gets = status, text, 0, 0
    def handle(self, key, kw):
        if key == "gmail.users.getProfile": self.profiles += 1; return {"historyId": f"p{self.profiles}"}
        if key == "gmail.users.history.list": self.stop(); raise HttpErr(self.status, self.text)
        if key == "gmail.users.messages.get": self.gets += 1
        return super().handle(key, kw)
URL404 = "<HttpError 503 when requesting https://gmail.googleapis.com/gmail/v1/users/me/history?startHistoryId=404404&pageToken=4040&alt=json returned \"Backend Error\">"
got, pg, sv, more = run_fake(lambda: Failing(ADA, 503, URL404), [UN])
check("expired history: a 503 whose text holds '404' leaves the cursor alone (no resync from getProfile), delivers nothing and asks for no second poll",
      sv["hist"] == "p2" and pg.profiles == 2 and got == [] and not more, (sv, pg.profiles, got, more))
got, pg, sv, more = run_fake(lambda: Failing(ADA, 429, URL404.replace("503", "429")), [UN])
check("expired history: a 429 with '404' in its URL leaves the cursor alone too", sv["hist"] == "p2" and pg.profiles == 2 and got == [], (sv, pg.profiles))
got, pg, sv, more = run_fake(lambda: Failing(ADA, 404, "Requested entity was not found."), [UN])
check("expired history: Google's own 404 (the status, with no '404' in the text) resyncs the cursor from getProfile", sv["hist"] == "p3" and pg.profiles == 3 and got == [], (sv, pg.profiles))
class StatusCode(Exception):
    status_code = 404
check("expired history: the status is read from resp.status, status_code or status, never from the text",
      gw.http_status(HttpErr(404, "x")) == 404 and gw.http_status(StatusCode("404")) == 404 and gw.http_status(types.SimpleNamespace(status=404)) == 404
      and gw.http_status(Exception("HTTP 404 /history?startHistoryId=404")) is None and gw.http_status(HttpErr(503, "404")) == 503, gw.http_status(HttpErr(503, "404")))

# ---- API calls per poll: no get for a mailbox nobody reads, a cap on gets per poll, and mail never delivered twice
class Many(Account):
    """A mailbox whose history is `n` records, "1".."n", each adding `per` mails (m<i>-<j>, thread t<i>-<j>), served `size` to a page; `inclusive` makes startHistoryId inclusive
    (the record at the cursor comes back). It counts its history.list and messages.get calls and stops the run after `stop_lists` history.list calls (a runaway guard)."""
    def __init__(self, email, n, per=1, size=500, inclusive=False, stop_lists=12, dup=False):
        super().__init__(email); self.size, self.inclusive, self.stop_lists, self.lists, self.gets, self.starts = size, inclusive, stop_lists, 0, 0, []
        self.n = n; self.recs = [{"id": str(i), "messagesAdded": [{"message": {"id": f"m{i}-{j}", "threadId": f"t{i}-{j}"}} for j in range(per)]} for i in range(1, n + 1)]
        if dup:      # the first record's mail is named again in every later record (a mail changed by a later event is added to the history again)
            for r in self.recs[1:]: r["messagesAdded"].append(self.recs[0]["messagesAdded"][0])
    def handle(self, key, kw):
        if key == "gmail.users.getProfile": return {"historyId": "0"}
        if key == "gmail.users.history.list":
            self.lists += 1
            if "pageToken" not in kw: self.starts.append(kw["startHistoryId"])
            s = int(kw["startHistoryId"]); todo = [r for r in self.recs if (int(r["id"]) >= s if self.inclusive else int(r["id"]) > s)]
            at = int(kw.get("pageToken", 0)); more = at + self.size < len(todo)
            if self.lists >= self.stop_lists: self.stop()
            return {"history": todo[at:at + self.size], **({"nextPageToken": str(at + self.size)} if more else {}), "historyId": str(self.n)}
        if key == "gmail.users.messages.get": self.gets += 1; return {**super().handle(key, kw), "snippet": kw["id"]}
        return super().handle(key, kw)
def ids(n, per=1): return [f"m{i}-{j}" for i in range(1, n + 1) for j in range(per)]
got, pg, sv, more = run_fake(lambda: Many(ADA, 10, stop_lists=1), ["gmail:q@home:from:pat"])
check("gets: a mailbox that no query anchor reads makes no messages.get call, and its cursor still moves on", pg.gets == 0 and got == [] and sv["hist"] == "10", (pg.gets, got, sv))
got, pg, sv, more = run_fake(lambda: Many(ADA, 10, stop_lists=1), ["gmail:q@home:from:pat", "gmail:t3-0"])
check("gets: a thread anchor needs the get for its own thread's mail and no other", pg.gets == 1 and got == [("gmail:t3-0", "m3-0")], (pg.gets, got))
got, pg, sv, more = run_fake(lambda: Many(ADA, 10, stop_lists=1), ["gmail:q@work:from:pat"])
check("gets: a query anchor that reads the mailbox gets every mail once", pg.gets == 10 and sorted(t for _a, t in got) == sorted(ids(10)), (pg.gets, got))
check("gets: the default cap is 200 and the default pages are 10", gw.MESSAGE_GETS == 200 and gw.HISTORY_PAGES == 10 and gw.HISTORY_PAGE == 500, (gw.MESSAGE_GETS, gw.HISTORY_PAGES))
got, pg, sv, more = run_fake(lambda: Many(ADA, 500), [UN], total=500)
check("cap: 500 added mails with the default cap take three polls", pg.lists == 3 and pg.starts == ["0", "200", "400"], (pg.lists, pg.starts))
check("cap: every mail is delivered exactly once, 500 gets in all, and no poll is left queued", sorted(t for _a, t in got) == sorted(ids(500)) and len(got) == 500 and pg.gets == 500 and not more, (len(got), pg.gets, more))
check("cap: the cursor ends at the history id Gmail reported", sv["hist"] == "500", sv)
got, pg, sv, more = run_fake(lambda: Many(ADA, 100, per=3), [UN], total=300)
check("cap: a record is never split: the poll stops before the record that would pass the cap, and the cursor is the last record handled whole",
      pg.starts == ["0", "66"] and pg.gets == 300 and sorted(t for _a, t in got) == sorted(ids(100, 3)) and len(got) == 300 and not more, (pg.starts, pg.gets, len(got), more))
got, pg, sv, more = run_fake(lambda: Many(ADA, 2, per=250), [UN], total=500)
check("cap: one record holding more mails than the cap is handled whole (the poll cannot stall), the next record in the next poll", pg.starts == ["0", "1"] and len(got) == 500 and pg.gets == 500, (pg.starts, len(got), pg.gets))
got, pg, sv, more = run_fake(lambda: Many(ADA, 6, inclusive=True), [UN], total=6, MESSAGE_GETS=2)
check("inclusive cursor: a repeated last record is neither fetched nor delivered again (capped polls)", pg.starts == ["0", "2", "4"] and pg.gets == 6 and sorted(t for _a, t in got) == sorted(ids(6)) and len(got) == 6, (pg.starts, pg.gets, got))
got, pg, sv, more = run_fake(lambda: Many(ADA, 6, size=2, inclusive=True), [UN], total=6, HISTORY_PAGES=2)
check("inclusive cursor: the record at a page cap repeats on the next poll and is delivered once", pg.starts == ["0", "4"] and sorted(t for _a, t in got) == sorted(ids(6)) and len(got) == 6 and pg.gets == 6, (pg.starts, pg.gets, got))
check("inclusive cursor: the handled mail is saved with the cursor, bounded", len(sv["sent"]) == 6 and set(sv["sent"]) == set(ids(6)), sv)
got, pg, sv, more = run_fake(lambda: Many(ADA, 12, stop_lists=1), [UN], SENT_KEEP=5)
check("inclusive cursor: only the last SENT_KEEP handled mails are kept", sv["sent"] == ids(12)[-5:], sv)
got, pg, sv, more = run_fake(lambda: Many(ADA, 3, size=1, dup=True), [UN], total=3)
check("dedupe: a mail named in several history records of one poll, also on different pages, is fetched and delivered once",
      pg.lists == 3 and pg.gets == 3 and sorted(t for _a, t in got) == ["m1-0", "m2-0", "m3-0"] and len(got) == 3, (pg.lists, pg.gets, got))
got, pg, sv, more = run_fake(lambda: Many(ADA, 3, dup=True), [UN], total=3)
check("dedupe: …and so when the records come on one page", pg.gets == 3 and sorted(t for _a, t in got) == ["m1-0", "m2-0", "m3-0"] and len(got) == 3, (pg.gets, got))
class NoId(Many):
    """History records that carry no id (Gmail gives every record one; the reader must not depend on it)."""
    def handle(self, key, kw):
        r = super().handle(key, kw)
        return {**r, "history": [{k: v for k, v in x.items() if k != "id"} for x in r["history"]]} if "history" in r else r
got, pg, sv, more = run_fake(lambda: NoId(ADA, 4, size=2, stop_lists=4), [UN], HISTORY_PAGES=1)
check("page cap: a last record with no id keeps the old cursor (no KeyError), and the mail read again is delivered once",
      sv["hist"] == "0" and pg.lists == 4 and sorted(t for _a, t in got) == ["m1-0", "m2-0"] and len(got) == 2 and pg.gets == 2, (sv, pg.lists, got))
got, pg, sv, more = run_fake(lambda: Many(ADA, 12, size=1), [UN], total=12)
check("pages: with the module's own bound (not set here) a poll reads ten pages of history and the next poll goes on from the last record read",
      pg.starts == ["0", "10"] and pg.lists == 12 and sorted(t for _a, t in got) == sorted(ids(12)) and len(got) == 12 and not more, (pg.starts, pg.lists, len(got), more))

# ---- a restart resumes from the saved read position (mail that arrives while the service is stopped is still delivered)
class Live(Many):
    """A Many whose getProfile answers the mailbox's current position (its last history id), as Gmail's does: a start that resets the cursor to `now` skips what the mailbox gained meanwhile."""
    def handle(self, key, kw):
        if key == "gmail.users.getProfile": return {"historyId": str(self.n)}
        return super().handle(key, kw)
got1, pg1, sv1, _m = run_fake(lambda: Live(ADA, 3, stop_lists=1), [UN])
check("restart: a first start (nothing saved) begins at now: the three mails there already are not delivered, and the position is saved", got1 == [] and sv1["hist"] == "3", (got1, sv1))
got2, pg2, sv2, _m = run_fake(lambda: Live(ADA, 5, stop_lists=1), [UN], saved=sv1)
check("restart: mail that arrived while the service was stopped is delivered after the restart, once (the saved position is kept, not reset to now)",
      sorted(t for _a, t in got2) == ["m4-0", "m5-0"] and len(got2) == 2 and sv2["hist"] == "5" and pg2.starts == ["3"], (got2, sv2, pg2.starts))

# ---- the tool text teaches the syntax
desc = server._ANCHORS_DESC
check("text: the tool description teaches the scope and says the list names the mailboxes", "gmail:q@<mailbox>:<query>" in desc and "every mailbox" in desc and "mailboxes each Gmail anchor reads" in desc, desc[:300])
check("text: the shapes a refusal lists include the scoped form", "gmail:q@<mailbox>:<query>" in server._ANCHOR_SHAPES, server._ANCHOR_SHAPES)

print(f"{len(ran)} checks, {len(fails)} failed")
sys.exit(1 if fails else 0)
