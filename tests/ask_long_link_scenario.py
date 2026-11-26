"""Scenario test for the refusal of an ask, or an option, that links a long page (decision_gates.long_link_hit, `_gate_ask_links`, `_gate_options`, config [ask] refuse_link_prefixes) — fixture data,
no live store, no network, no server socket. Every host is an example.invalid one.

  1  the matcher (long_link_hit): a bare address and a [words](url) link, the scheme and host in any case, http and https alike, a default port, a fragment, a /tree/ page as its /blob/ form, a prefix with no path
     meaning its host (a lookalike host is no hit), a prefix without a closing slash ending at a path segment, trailing sentence punctuation, the first listed link of several, an unlisted link, none listed
  2  the config reader: a list, one string, junk entries dropped, a missing or misshaped key reads as none
  3  the write gate: create and update refuse an ask that sets a listed link (markdown, bare, mixed case, /blob/ and /tree/), an option that holds one, and an ask the first line of next carries; the refusal text is pinned;
     an unlisted link, a mockup link and a claude.ai artifact are accepted; an update that sets no ask leaves a stored old ask alone; an empty list changes nothing
  4  the tool text and the docs say it

    uv run tests/ask_long_link_scenario.py        → exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="longlink-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml = _instance.set_person(toml)
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite's writes replace next wholesale; the checklist has its own suite
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-front", "team-back", "home-stew")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time(); H = 3600.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "seen": now0} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active",
                                                                                "board": [], "board_open": 0, "agents": {"home-front": "the front", "team-back": "the back"}, "back_agents": {"team-back": "the back"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
(T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 100 * 86400, "seen": {}, "reported": []}))

def item(i, status="open", desc=None, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] settings layout {i}", "description": desc or DESC, "status": status, "updated": now0 - 3 * H,
                                                      "state_updated": now0 - 3 * H, "confirmed": now0 - 3 * H,
                                                      "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "Oliver: answer the ask", **meta}}))
def rd(i): return json.loads((T / (f"store/{i[0]}/{i[1:]}.json" if isinstance(i, str) else f"store/a/{i}.json")).read_text())
raw = lambda i: (T / f"store/a/{i}.json").read_text()
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except Exception as e:
        check(name, all(w in str(e) for w in want), str(e))
def refused_nw(name, i, f, *want):
    was = raw(i); refused(name, f, *want); check(name + " (nothing written)", raw(i) == was, None)

DESC = "- A new layout for the settings page\n- Done when the layout is picked"
ASK = "Decide: ship the new settings layout? · Recommend: yes · Stakes: low · By: Fri"
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route
from stackshot.service import update as _update_svc
from stackshot.core import config as _cfg
from stackshot.core.instance import OWNER
from stackshot.model import decision_gates as _dg
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import create as _wt_create
from stackshot.service import telling
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
telling.tell_woken = lambda *a, **k: None
upd = lambda i, sender="home-front", **kw: _update_svc._update(f"a{i}", sender=sender, **kw)
mk = lambda **kw: _wt_create._create(**{"subject": "[home] pick the settings layout", "description": DESC, "project": "projects/alpha", "owner": "home-front",
                                    "next": "Oliver: answer the ask", "needs": ["decision"], "ask": ASK, **kw})

NOTES = "https://notes.example.invalid/projects/"
GIT = "https://git.example.invalid/org/brain/blob/main/projects/"
WIKI = "https://wiki.example.invalid"
PAGE = "https://docs.example.invalid/page"
PREFIXES = [NOTES, GIT, WIKI, PAGE]
LONG = NOTES + "alpha"
ART = "https://claude.ai/artifact/00000000-0000-4000-8000-000000000053"
MOCK_HOST = "tool.example.invalid"
MOCK = f"https://{MOCK_HOST}/mockup/12"
SHORT = "https://short.example.invalid/decision/7"
hit = lambda text, pre=None: _dg.long_link_hit(text, PREFIXES if pre is None else pre)
def ask_with(link, tail=""): return f"Decide: ship the new layout [plan]({link}){tail}? · Recommend: yes · Stakes: low · By: Fri"
def refusal(link, where="the ask"):
    return (f"Refused: {where} links a long page ({link}), not a decision page. {OWNER} decides from the page the ask links, so link a short decision page made for this decision: "
            "an artifact, a document, or a mockup page from the web UI, with the decision, its choices and what is at stake on it. The long page stays on the project page, not in the ask or its options.")

# ================================================================ 1. the matcher
check("1 a bare address is a hit", hit(f"see {LONG} now") == LONG)
check("1 a markdown link is a hit, its address as written", hit(f"see [the notes]({LONG}) now") == LONG)
check("1 scheme and host in any case", hit("HTTPS://Notes.Example.INVALID/projects/alpha") == "HTTPS://Notes.Example.INVALID/projects/alpha")
check("1 the path is matched as written (a path in another case is another page)", hit("https://notes.example.invalid/Projects/alpha") == "")
check("1 http and https are the same page", hit("http://notes.example.invalid/projects/alpha") != "" and hit("https://notes.example.invalid/projects/alpha") != "")
check("1 a default port is dropped, another port is another host", hit("https://notes.example.invalid:443/projects/a") != "" and hit("https://notes.example.invalid:8443/projects/a") == "")
check("1 a fragment and a query do not hide a hit", hit(LONG + "#section") != "" and hit(LONG + "?v=2") != "")
check("1 a /tree/ link is the same page as a listed /blob/ prefix", hit("https://git.example.invalid/org/brain/tree/main/projects/p1") != "" and hit(GIT + "p1.md") != "")
check("1 a listed /tree/ prefix takes a /blob/ link", hit("https://git.example.invalid/org/brain/blob/main/projects/p1", ["https://git.example.invalid/org/brain/tree/main/projects/"]) != "")
check("1 another folder of the same repository is no hit", hit("https://git.example.invalid/org/brain/blob/main/infra/ax.md") == "")
check("1 a prefix with no path means its host: every page of it is a hit", hit("https://wiki.example.invalid/any/page") != "" and hit("https://WIKI.example.invalid") != "")
check("1 …and a lookalike host is no hit", hit("https://wiki.example.invalid.evil.example/x") == "" and hit("https://wiki.example.invalidx/x") == "")
check("1 a prefix without a closing slash ends at a path segment: the page and what is under it", hit("https://docs.example.invalid/page") != "" and hit("https://docs.example.invalid/page/sub") != "" and hit("https://docs.example.invalid/page?x=1") != "")
check("1 …and a page whose name only starts the same is no hit", hit("https://docs.example.invalid/pages") == "" and hit("https://docs.example.invalid/page-two") == "")
check("1 trailing sentence punctuation is not part of the address", hit(f"read {LONG}.") == LONG and hit(f"read {LONG},") == LONG)
check("1 an address in angle brackets or quotes is read", hit(f"<{LONG}>") == LONG and hit(f'"{LONG}"') == LONG)
check("1 the first listed link of several is the hit, an unlisted one before it is skipped", hit(f"{SHORT} and {LONG} and {GIT}x") == LONG)
check("1 an unlisted link is no hit", hit(f"[x]({SHORT})") == "" and hit(f"[a]({ART})") == "" and hit(f"[m]({MOCK})") == "")
check("1 text with no link, an empty text and None are no hit", hit("Decide: ship it") == "" and hit("") == "" and hit(None) == "")
check("1 no list, an empty list: nothing is a hit", hit(LONG, []) == "" and hit(LONG, ()) == "")
check("1 an entry that is no address is ignored, the others stand", hit(LONG, ["", "notes", 5, None, NOTES]) == LONG and hit(LONG, ["", "notes", 5]) == "")
check("1 a hit is cut at 80 characters", len(hit(NOTES + "a" * 200)) == 80)

# ================================================================ 2. the config reader
cfg_ask = _cfg.CFG.setdefault("ask", {}); had = "refuse_link_prefixes" in cfg_ask; was = cfg_ask.get("refuse_link_prefixes")
def setk(v):
    if v is KeyError: cfg_ask.pop("refuse_link_prefixes", None)
    else: cfg_ask["refuse_link_prefixes"] = v
setk(KeyError); check("2 a missing key reads as none", _cfg.ask_refuse_link_prefixes() == ())
setk([]); check("2 an empty list reads as none", _cfg.ask_refuse_link_prefixes() == ())
setk([NOTES, "  " + GIT + "  "]); check("2 a list is read, entries stripped", _cfg.ask_refuse_link_prefixes() == (NOTES, GIT), _cfg.ask_refuse_link_prefixes())
setk(NOTES); check("2 one string is one prefix", _cfg.ask_refuse_link_prefixes() == (NOTES,))
setk(["", "notes.example.invalid/projects/", "ftp://x.example.invalid/", "https://", "https://a b/c", 7, None, NOTES]); check("2 an entry that is no http(s) address is dropped", _cfg.ask_refuse_link_prefixes() == (NOTES,), _cfg.ask_refuse_link_prefixes())
setk(7); check("2 a misshaped key reads as none", _cfg.ask_refuse_link_prefixes() == ())
setk({"a": 1}); check("2 a table reads as none", _cfg.ask_refuse_link_prefixes() == ())
setk(PREFIXES); check("2 the matcher reads the instance's list when none is given", _dg.long_link_hit(LONG) == LONG)
setk([]); check("2 …and an empty list refuses nothing", _dg.long_link_hit(LONG) == "")

# ================================================================ 3. the write gate
OPTS = [{"label": "Approve", "line": "Ship the new layout.", "recommended": True}, {"label": "Decline", "line": "Keep the old one.", "recommended": False}]
def opts_with(line): return [{"label": "Approve", "line": line, "recommended": True}, OPTS[1]]
setk(PREFIXES)
cfg_cl = _cfg.CFG.setdefault("client", {}); was_mock = cfg_cl.get("mockup_hosts"); cfg_cl["mockup_hosts"] = [MOCK_HOST]

for link, name in ((LONG, "a markdown link"), ("HTTPS://NOTES.Example.Invalid/projects/alpha", "a mixed-case host"), (GIT + "alpha.md", "a /blob/ link"),
                   ("https://git.example.invalid/org/brain/tree/main/projects/alpha.md", "a /tree/ link"), ("https://wiki.example.invalid/x", "a host-only prefix")):
    refused(f"3 create: an ask with {name} is refused, with the pinned words", lambda link=link: mk(ask=ask_with(link)), refusal(link))
    item(1, needs=["decision"], ask=ASK, mover="Oliver", then="team-back")
    refused_nw(f"3 update: an ask with {name} is refused, with the pinned words", 1, lambda link=link: upd(1, ask=ask_with(link)), refusal(link))
    check(f"3 update: …the stored ask is as it was", rd(1)["metadata"]["ask"] == ASK, rd(1)["metadata"])

e = ""
try: mk(ask=f"Decide: ship the new layout {LONG}? · Recommend: yes · Stakes: low · By: Fri")
except Exception as ex: e = str(ex)
check("3 create: a bare address in the ask is refused for the long page too", refusal(LONG) in e, e)
e = ""
try: mk(ask="Decide: ship it · Recommend: yes · Stakes: " + LONG + " · By: Fri")
except Exception as ex: e = str(ex)
check("3 create: a link in any part of the ask counts", refusal(LONG) in e, e)
e = ""
try: mk(ask="not in the form " + LONG)
except Exception as ex: e = str(ex)
check("3 create: an ask that is also misshaped is refused for the link first, the shape advice would hand the link back", e == refusal(LONG), e)

refused("3 create: an option with a listed link is refused, naming the option, with the same words", lambda: mk(options=opts_with(f"Ship it, see [notes]({LONG}).")), refusal(LONG, "option 1 (Approve)"))
refused("3 create: …a bare address in the second option", lambda: mk(options=[OPTS[0], {"label": "Decline", "line": f"Keep it, see {LONG}", "recommended": False}]), refusal(LONG, "option 2 (Decline)"))
refused("3 create: …a listed link in the label of an option", lambda: mk(options=[{"label": f"See {LONG}", "line": "Ship the new layout.", "recommended": True}, OPTS[1]]), refusal(LONG, f"option 1 (See {LONG})"))
refused("3 create: an option with an unlisted link is still refused as before", lambda: mk(options=opts_with(f"Ship it, see [x]({SHORT}).")), "Refused", "option 1", "clickable card")
item(2, needs=["decision"], ask=ASK, mover="Oliver", then="team-back")
refused_nw("3 update: an option with a listed link is refused", 2, lambda: upd(2, options=opts_with(f"see [notes]({LONG})")), refusal(LONG, "option 1 (Approve)"))

for link, name in ((SHORT, "an unlisted link"), (ART, "a claude.ai artifact page"), (MOCK, "a mockup page of the web UI"), ("https://notes.example.invalid/other/alpha", "another folder of the same host")):
    out = mk(ask=ask_with(link))
    check(f"3 create: an ask with {name} is accepted", bool(re.match(r"created \w\d+", out)) and link in rd((re.match(r"created (\w\d+)", out) or [0, ""])[1])["metadata"]["ask"], out[:300])
    item(3, needs=["decision"], ask=ASK, mover="Oliver", then="team-back")
    upd(3, ask=ask_with(link))
    check(f"3 update: an ask with {name} is accepted", rd(3)["metadata"]["ask"] == ask_with(link), rd(3)["metadata"])
out = mk(options=OPTS)
check("3 create: clean options and an ask with no link are accepted", bool(re.match(r"created \w\d+", out)), out[:300])

# an ask only stored is never judged: an update that sets no ask is untouched
item(4, needs=["decision"], ask=ask_with(LONG), options=OPTS, mover="Oliver", then="team-back")
upd(4, priority="p2")
check("3 update: a priority change leaves a stored ask that links a listed page alone", rd(4)["metadata"]["ask"] == ask_with(LONG), rd(4)["metadata"])
upd(4, description="- A new layout for the settings page\n- Done when a layout is picked", next="Oliver: answer the ask, he has the page")
check("3 update: a description and next change leave it alone too", rd(4)["metadata"]["ask"] == ask_with(LONG) and "he has the page" in rd(4)["metadata"]["next"], rd(4)["metadata"])
upd(4, options=opts_with("Ship the new layout now."))
check("3 update: a change of the options alone leaves the stored ask alone", rd(4)["metadata"]["ask"] == ask_with(LONG) and rd(4)["metadata"]["options"][0]["line"] == "Ship the new layout now.", rd(4)["metadata"])
refused_nw("3 update: rewriting the stored ask with the listed link again is a write that sets it, and is refused", 4, lambda: upd(4, ask=ask_with(LONG)), refusal(LONG))
upd(4, ask=ask_with(SHORT))
check("3 update: rewriting it with a short decision page is accepted", rd(4)["metadata"]["ask"] == ask_with(SHORT), rd(4)["metadata"])
upd(4, clear_ask=True, needs=["team-back"], next="team-back: carry on", mover="team-back")
check("3 update: clearing the ask is never judged", not rd(4)["metadata"].get("ask"), rd(4)["metadata"])

# a client with no ask parameter writes the ask as the first line of next
e = ""
try: mk(ask="", next=ask_with(LONG) + "\nOliver: answer the ask")
except Exception as ex: e = str(ex)
check("3 create: the ask carried as the first line of next is judged as an ask", refusal(LONG) in e, e)
out = mk(ask="", next=ask_with(SHORT) + "\nOliver: answer the ask")
check("3 create: …and one with a short decision page is taken as the ask", bool(re.match(r"created \w\d+", out)) and "taken as the ask" in out, out[:300])
item(6, needs=["decision"], ask=ASK, mover="Oliver", then="team-back")
was6 = raw(6)
try: upd(6, next=ask_with(LONG) + "\nOliver: answer the ask"); e = ""
except Exception as ex: e = str(ex)
check("3 update: …and on an update", refusal(LONG) in e and raw(6) == was6, e)

# an empty list changes nothing
setk([])
out = mk(ask=ask_with(LONG))
check("3 an empty list: an ask with any link is accepted, as before", bool(re.match(r"created \w\d+", out)), out[:300])
item(7, needs=["decision"], ask=ASK, mover="Oliver", then="team-back"); upd(7, ask=ask_with(LONG))
check("3 …on an update too", rd(7)["metadata"]["ask"] == ask_with(LONG), rd(7)["metadata"])
e = ""
try: mk(options=opts_with(f"see [notes]({LONG})"))
except Exception as ex: e = str(ex)
check("3 an empty list: an option with a link is refused the old way, with no word of a long page", "clickable card" in e and "long page" not in e, e)
setk(KeyError)
out = mk(ask=ask_with(LONG))
check("3 no key at all: nothing is refused", bool(re.match(r"created \w\d+", out)), out[:300])

# ================================================================ 4. the text and the docs
snap = json.loads(pathlib.Path(STACK, "tests/tool_text.snapshot.json").read_text(encoding="utf-8"))["tools"]
for tool in ("create", "update"):
    d = json.dumps(snap[tool], ensure_ascii=False)
    check(f"4 text: {tool} says an ask's link is a short decision page, never a long project or notes page", "A link in the ask goes to a short decision page made for it (an artifact, a document or a mockup page), never a long project or notes page." in d, tool)
    check(f"4 text: {tool} says the instance may refuse such a link in an ask or an option", "where the instance lists such pages, an ask or an option that links one is refused when the write sets it" in d, tool)
doc = pathlib.Path(STACK, "docs/configuration.md").read_text(encoding="utf-8")
check("4 docs: the config key is in the configuration table", "`ask.refuse_link_prefixes` | `[]`" in doc)
check("4 docs: the key is in the example file with an empty list", re.search(r"(?m)^refuse_link_prefixes = \[\]", pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")) is not None)
check("4 docs: the asks page has the rule", "A decision's link is a short decision page" in pathlib.Path(STACK, "docs/asks-and-answers.md").read_text(encoding="utf-8"))

setk(was) if had else setk(KeyError)
if was_mock is None: cfg_cl.pop("mockup_hosts", None)
else: cfg_cl["mockup_hosts"] = was_mock
import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": ask long-link scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
