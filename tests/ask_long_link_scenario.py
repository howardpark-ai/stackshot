"""Scenario test for the refusal of an ask, or an option, that links a long page (decision_gates.long_link_hit, `_gate_ask_links`, `_gate_options`, config [ask] refuse_link_prefixes) — fixture data,
no live store, no network, no server socket. Every host is an example.invalid one.

  1  the matcher (long_link_hit): a bare address and a [words](url) link, the scheme and host in any case, http and https alike, a default port, a fragment, a /tree/ page as its /blob/ form, a prefix with no path
     meaning its host (a lookalike host is no hit), a prefix without a closing slash ending at a path segment, trailing sentence punctuation, the first listed link of several, an unlisted link, none listed
  2  the config reader: a list, one string, junk entries dropped, a missing or misshaped key reads as none
  3  the write gate: create and update refuse an ask that sets a listed link (markdown, bare, mixed case, /blob/ and /tree/), an option that holds one, and an ask the first line of next carries; the refusal text is pinned;
     an unlisted link, a mockup link and a claude.ai artifact are accepted; an update that sets no ask leaves a stored old ask alone; an empty list changes nothing
  3b the script exemption: the question route (and any write the question flag marks) and the cold call's own write (the server's per-write flag, set in a try/finally) take a listed link in an ask, a link in an
     option stays refused; the update TOOL with sender "cold-call" (or any sender label) is refused all the same; the repeat of a stored ask as the first line of next is no write of the ask (not judged), a changed one is
  3c the defaults: _gate_ask and _gate_options judge links when called with no links argument
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
def attempt(f):
    """(result, "") when f runs, (None, the error) when it raises: a check reads the error, the run never aborts on it."""
    try: return f(), ""
    except Exception as e: return None, f"{e.__class__.__name__}: {e}"
def created(f):
    out, err = attempt(f); return out, bool(re.match(r"created \w\d+", str(out or ""))), err or str(out)[:300]
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
from stackshot.web.tools import update as _wt_update
from stackshot.service import asks as _asks
from stackshot.service import wait_gates as _wait_gates
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
    head = f"Refused: {where} links a long page ({link}), not a decision page. {OWNER} decides from the page the ask links, so "
    if where != "the ask":      # an option holds no link: the short link goes in the ask's Decide part
        return (head + "take the link out of the option and put the link to a short decision page in the ask's Decide part: an artifact, a document, or a mockup page from the web UI, made for this decision, "
                "with the decision, its choices and what is at stake on it. The long page stays on the project page, not in the ask or its options. The option's line says in words what it is.")
    return (head + "link a short decision page made for this decision: "
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

# one address in its cheap spellings meets its prefix (each spelling a check of its own; the link and the prefix are put in one form alike)
check("1 /tree and /blob alike: a prefix ending in /tree with no closing slash takes a /tree/ link and a /blob/ link", hit("https://git.example.invalid/org/brain/tree/main/x", ["https://git.example.invalid/org/brain/tree"]) != ""
      and hit("https://git.example.invalid/org/brain/blob/main/x", ["https://git.example.invalid/org/brain/tree"]) != "")
check("1 /tree and /blob alike: a prefix ending in /blob with no closing slash takes both forms", hit("https://git.example.invalid/org/brain/tree/main/x", ["https://git.example.invalid/org/brain/blob"]) != ""
      and hit("https://git.example.invalid/org/brain/blob/main/x", ["https://git.example.invalid/org/brain/blob"]) != "")
check("1 /tree and /blob alike: with a closing slash, both ways", hit("https://git.example.invalid/org/brain/tree/main/x", ["https://git.example.invalid/org/brain/tree/"]) != ""
      and hit("https://git.example.invalid/org/brain/blob/main/x", ["https://git.example.invalid/org/brain/tree/"]) != ""
      and hit("https://git.example.invalid/org/brain/tree/main/x", ["https://git.example.invalid/org/brain/blob/"]) != "")
check("1 /tree and /blob alike: a link that ends at /tree, and a prefix whose name only starts the same, are told apart", hit("https://git.example.invalid/org/brain/tree", ["https://git.example.invalid/org/brain/blob"]) != ""
      and hit("https://git.example.invalid/org/brain/trees/x", ["https://git.example.invalid/org/brain/tree"]) == "")
check("1 only the first tree or blob segment is read as blob: a folder named tree further down is a folder", hit("https://git.example.invalid/org/brain/blob/main/tree/x", ["https://git.example.invalid/org/brain/blob/main/blob/"]) == "")
check("1 dot segments are resolved: /./ and /../ in the link", hit("https://notes.example.invalid/./projects/alpha") != "" and hit("https://notes.example.invalid/other/../projects/alpha") != ""
      and hit("https://notes.example.invalid/projects/x/../../other/y") == "" and hit("https://notes.example.invalid/projects/alpha/..") != "" and hit("https://notes.example.invalid/projects/./") != "")
check("1 …a .. at the root stays at the root, and a .. that leaves a listed folder leaves it", hit("https://notes.example.invalid/../projects/alpha") != "" and hit("https://notes.example.invalid/projects/../other") == "")
check("1 …and in the prefix", hit(LONG, ["https://notes.example.invalid/x/../projects/"]) == LONG)
check("1 a run of slashes is one slash, in the link and in the prefix", hit("https://notes.example.invalid//projects///alpha") != "" and hit(LONG, ["https://notes.example.invalid//projects//"]) == LONG)
check("1 an escape of a plain character is decoded: %70rojects, %2e%2e and the upper and lower case of the hex", hit("https://notes.example.invalid/%70rojects/alpha") != "" and hit("https://notes.example.invalid/%50rojects/alpha") == ""
      and hit("https://notes.example.invalid/other/%2e%2e/projects/alpha") != "" and hit("https://notes.example.invalid/other/%2E%2E/projects/alpha") != "" and hit(LONG, ["https://notes.example.invalid/%70rojects/"]) == LONG)
check("1 %2F is a slash, in the link and in the prefix", hit("https://notes.example.invalid/projects%2Falpha") != "" and hit("https://notes.example.invalid%2Fprojects/alpha") == "" and hit("https://notes.example.invalid/projects%2falpha") != ""
      and hit(LONG, ["https://notes.example.invalid%2Fprojects/"]) == "" and hit(LONG, ["https://notes.example.invalid/projects%2F"]) == LONG)
check("1 any other escape is kept as written, its hex in one case", hit("https://docs.example.invalid/page/a%3a", ["https://docs.example.invalid/page/a%3A"]) != "" and hit("https://docs.example.invalid/page/a%3a", ["https://docs.example.invalid/page/a:"]) == ""
      and hit("https://notes.example.invalid/projects/%252Falpha") != "" and hit("https://notes.example.invalid/%2570rojects/alpha") == "")
check("1 a closing dot on the host is no other host, in the link and in the prefix", hit("https://notes.example.invalid./projects/alpha") != "" and hit("https://Notes.Example.Invalid.:443/projects/a") != ""
      and hit(LONG, ["https://notes.example.invalid./projects/"]) == LONG and hit("https://notes.example.invalid.evil.example/projects/a") == "")
check("1 a backslash in the path is a slash, in the link and in the prefix", hit("https://notes.example.invalid\\projects\\alpha") != "" and hit("https://notes.example.invalid/projects\\alpha") != ""
      and hit(LONG, ["https://notes.example.invalid\\projects\\"]) == LONG and hit("https://notes.example.invalid/other?next=\\projects\\alpha") == "")
GH = "https://github.com/Org/Brain/blob/main/projects/"
check("1 github.com: owner and repository in any case, in the link and in the prefix", hit("https://github.com/org/brain/blob/main/projects/p1", [GH]) != "" and hit("https://GitHub.com/ORG/BRAIN/tree/main/projects/p1", [GH]) != ""
      and hit("https://github.com/org/brain/blob/main/projects/p1", ["https://github.com/org/brain/blob/main/projects/"]) != "" and hit("https://www.github.com/org/brain/blob/main/projects/p1", ["https://www.github.com/ORG/Brain/"]) != "")
check("1 …a branch and a file name keep their case, another repository is another page, and another host keeps every case", hit("https://github.com/org/brain/blob/main/Projects/p1", [GH]) == "" and hit("https://github.com/org/brain/blob/Main/projects/p1", [GH]) == ""
      and hit("https://github.com/org/other/blob/main/projects/p1", [GH]) == "" and hit("https://git.example.invalid/ORG/brain/blob/main/projects/p1", ["https://git.example.invalid/org/brain/blob/main/projects/"]) == "")
Q = "https://docs.example.invalid/q?id=1"
check("1 a prefix with a query takes that query, a longer query pair and the same with a fragment, and no other query", hit(Q, [Q]) != "" and hit(Q + "&x=2", [Q]) != "" and hit(Q + "#top", [Q]) != ""
      and hit("https://docs.example.invalid/q?id=2", [Q]) == "" and hit("https://docs.example.invalid/q?id=10", [Q]) == "" and hit("https://docs.example.invalid/q", [Q]) == "" and hit("https://docs.example.invalid/q/sub?id=1", [Q]) == "")
check("1 a link with a query still takes a prefix with none, and the query is kept as written", hit("https://docs.example.invalid/page?id=7&x=1") != "" and hit("https://docs.example.invalid/page/sub?id=7") != "" and hit("https://docs.example.invalid/q?ID=1", [Q]) == "")
check("1 a fragment on the prefix is dropped", hit("https://docs.example.invalid/page/sub", ["https://docs.example.invalid/page#top"]) != "" and hit("https://docs.example.invalid/pages", ["https://docs.example.invalid/page#top"]) == "")
check("1 a host with no path in the link meets a prefix that ends in a slash", hit("https://wiki.example.invalid", ["https://wiki.example.invalid/"]) != "" and hit("https://wiki.example.invalid?x=1", ["https://wiki.example.invalid/"]) != "" and hit("https://wiki.example.invalid/", ["https://wiki.example.invalid"]) != "")
check("1 an address with no host is no prefix and no link, however it is spelled", hit("see https:///projects/x", [""]) == "" and hit("see https:///projects/x", ["https:///"]) == "" and hit("see https:///projects/x", ["https:///projects/"]) == ""
      and hit("see https://:80/projects/x", ["https://:80/"]) == "")
check("1 the words of a [words](url) link are an address too: a link text that is a listed address is refused, whatever the link is", hit(f"[{LONG}]({SHORT})") == LONG and hit(f"[see this]({SHORT})") == "")
check("1 a port that is no number is no address", hit("https://notes.example.invalid:abc/projects/x") == "")
check("1 a user name before the host does not hide a hit, and is no part of the host: it is ignored in the link and in the prefix", hit("https://user@notes.example.invalid/projects/alpha") != "" and hit("https://user:pw@notes.example.invalid/projects/alpha") != ""
      and hit(LONG, ["https://user@notes.example.invalid/projects/"]) == LONG and hit("https://user@notes.example.invalid.evil.example/projects/alpha") == "")
# a prefix that ends with a slash is the folder: its own link without the closing slash is a hit (and what only starts the same is not)
FOLDER = "https://git.example.invalid/org/brain/blob/main/projects/"
check("1 a prefix that ends with / takes the folder's own link without the closing slash, in the /tree/ form too", hit("https://git.example.invalid/org/brain/blob/main/projects", [FOLDER]) != ""
      and hit("https://git.example.invalid/org/brain/tree/main/projects", [FOLDER]) != "" and hit("https://notes.example.invalid/projects") != "" and hit(NOTES[:-1], [NOTES]) == NOTES[:-1])
check("1 …with a query or a fragment on the folder's link", hit(NOTES[:-1] + "?v=2", [NOTES]) != "" and hit(NOTES[:-1] + "#top", [NOTES]) != "" and hit(NOTES[:-1] + "/", [NOTES]) != "")
check("1 …and a page whose name only starts like the folder is no hit", hit(NOTES[:-1] + "x", [NOTES]) == "" and hit(NOTES[:-1] + "-old/a", [NOTES]) == "" and hit("https://notes.example.invalid", [NOTES]) == "")
check("1 …a prefix with a query that happens to end with / is no folder", hit("https://docs.example.invalid/q?next=", ["https://docs.example.invalid/q?next=/"]) == "" and hit("https://docs.example.invalid/q?next=/", ["https://docs.example.invalid/q?next=/"]) != "")
check("1 …the folder rule never takes another host or a longer first segment", hit("https://notes.example.invalid.evil.example/projects", [NOTES]) == "" and hit("https://notes.example.invalid/projectsx", [NOTES]) == "")
# the normal form of a link that ends in a dot segment: the closing slash stays (a /. or /.. at the end names the folder)
LN = _dg._link_norm
check("1 a link that ends in /. is the folder: the closing slash stays", LN("https://h.example.invalid/a/b/.") == "https://h.example.invalid/a/b/" and LN("https://h.example.invalid/a/b/./.") == "https://h.example.invalid/a/b/")
check("1 a link that ends in /.. is the parent folder: the closing slash stays", LN("https://h.example.invalid/a/b/c/..") == "https://h.example.invalid/a/b/" and LN("https://h.example.invalid/a/..") == "https://h.example.invalid/"
      and LN("https://h.example.invalid/..") == "https://h.example.invalid/")
check("1 a dot segment in the middle adds no slash", LN("https://h.example.invalid/a/./b") == "https://h.example.invalid/a/b" and LN("https://h.example.invalid/a/x/../b") == "https://h.example.invalid/a/b")
# the residual limits, pinned so the docs say what the code does
check("1 limits: a percent-encoded or fullwidth host, https:///host and https:/host are not read as the listed host", hit("https://%6eotes.example.invalid/projects/alpha") == "" and hit("https://\uff4eotes.example.invalid/projects/alpha") == ""
      and hit("https:///notes.example.invalid/projects/alpha") == "" and hit("https:/notes.example.invalid/projects/alpha") == "")
check("1 limits: other spellings of one page are other addresses (/raw/, /blame/, /edit/, a raw host, .git)", hit("https://git.example.invalid/org/brain/raw/main/projects/p1", [FOLDER]) == "" and hit("https://git.example.invalid/org/brain/blame/main/projects/p1", [FOLDER]) == ""
      and hit("https://git.example.invalid/org/brain/edit/main/projects/p1", [FOLDER]) == "" and hit("https://raw.git.example.invalid/org/brain/main/projects/p1", [FOLDER]) == "" and hit("https://git.example.invalid/org/brain.git/blob/main/projects/p1", [FOLDER]) == "")
check("1 limits: a prefix with a query takes that query as written, in its order only", hit("https://docs.example.invalid/q?a=1&b=2", ["https://docs.example.invalid/q?a=1&b=2"]) != "" and hit("https://docs.example.invalid/q?b=2&a=1", ["https://docs.example.invalid/q?a=1&b=2"]) == "")
check("1 limits: a prefix that holds ( ) [ ] \" ' or a backtick never matches, the link reader stops there", all(hit("https://docs.example.invalid/p" + c + "x", ["https://docs.example.invalid/p" + c + "x"]) == "" for c in "()[]\"'`"))
check("1 limits: %2F, a run of slashes and /tree/ for /blob/ are made equal on every host (too wide fails closed)", hit("https://docs.example.invalid/page%2Fx", ["https://docs.example.invalid/page/"]) != "" and hit("https://docs.example.invalid/page//x", ["https://docs.example.invalid/page/"]) != ""
      and hit("https://docs.example.invalid/tree/x", ["https://docs.example.invalid/blob/"]) != "")

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
    out, ok, why = created(lambda link=link: mk(ask=ask_with(link)))
    check(f"3 create: an ask with {name} is accepted", ok and link in rd(re.match(r"created (\w\d+)", out)[1])["metadata"]["ask"], why)
    item(3, needs=["decision"], ask=ASK, mover="Oliver", then="team-back")
    _, err = attempt(lambda link=link: upd(3, ask=ask_with(link)))
    check(f"3 update: an ask with {name} is accepted", rd(3)["metadata"]["ask"] == ask_with(link), err or rd(3)["metadata"])
out, ok, why = created(lambda: mk(options=OPTS))
check("3 create: clean options and an ask with no link are accepted", ok, why)

# an ask only stored is never judged: an update that sets no ask is untouched
item(4, needs=["decision"], ask=ask_with(LONG), options=OPTS, mover="Oliver", then="team-back")
_, err = attempt(lambda: upd(4, priority="p2"))
check("3 update: a priority change leaves a stored ask that links a listed page alone", rd(4)["metadata"]["ask"] == ask_with(LONG), err or rd(4)["metadata"])
_, err = attempt(lambda: upd(4, description="- A new layout for the settings page\n- Done when a layout is picked", next="Oliver: answer the ask, he has the page"))
check("3 update: a description and next change leave it alone too", rd(4)["metadata"]["ask"] == ask_with(LONG) and "he has the page" in rd(4)["metadata"]["next"], err or rd(4)["metadata"])
_, err = attempt(lambda: upd(4, options=opts_with("Ship the new layout now.")))
check("3 update: a change of the options alone leaves the stored ask alone", rd(4)["metadata"]["ask"] == ask_with(LONG) and rd(4)["metadata"]["options"][0]["line"] == "Ship the new layout now.", err or rd(4)["metadata"])
refused_nw("3 update: rewriting the stored ask with the listed link again is a write that sets it, and is refused", 4, lambda: upd(4, ask=ask_with(LONG)), refusal(LONG))
_, err = attempt(lambda: upd(4, ask=ask_with(SHORT)))
check("3 update: rewriting it with a short decision page is accepted", rd(4)["metadata"]["ask"] == ask_with(SHORT), err or rd(4)["metadata"])
_, err = attempt(lambda: upd(4, clear_ask=True, needs=["team-back"], next="team-back: carry on", mover="team-back"))
check("3 update: clearing the ask is never judged", not rd(4)["metadata"].get("ask"), err or rd(4)["metadata"])

# a client with no ask parameter writes the ask as the first line of next
e = ""
try: mk(ask="", next=ask_with(LONG) + "\nOliver: answer the ask")
except Exception as ex: e = str(ex)
check("3 create: the ask carried as the first line of next is judged as an ask", refusal(LONG) in e, e)
out, ok, why = created(lambda: mk(ask="", next=ask_with(SHORT) + "\nOliver: answer the ask"))
check("3 create: …and one with a short decision page is taken as the ask", ok and "taken as the ask" in out, why)
item(6, needs=["decision"], ask=ASK, mover="Oliver", then="team-back")
was6 = raw(6)
try: upd(6, next=ask_with(LONG) + "\nOliver: answer the ask"); e = ""
except Exception as ex: e = str(ex)
check("3 update: …and on an update", refusal(LONG) in e and raw(6) == was6, e)

# an empty list changes nothing
setk([])
out, ok, why = created(lambda: mk(ask=ask_with(LONG)))
check("3 an empty list: an ask with any link is accepted, as before", ok, why)
item(7, needs=["decision"], ask=ASK, mover="Oliver", then="team-back"); _, err = attempt(lambda: upd(7, ask=ask_with(LONG)))
check("3 …on an update too", rd(7)["metadata"]["ask"] == ask_with(LONG), err or rd(7)["metadata"])
e = ""
try: mk(options=opts_with(f"see [notes]({LONG})"))
except Exception as ex: e = str(ex)
check("3 an empty list: an option with a link is refused the old way, with no word of a long page", "clickable card" in e and "long page" not in e, e)
setk(KeyError)
out, ok, why = created(lambda: mk(ask=ask_with(LONG)))
check("3 no key at all: nothing is refused", ok, why)

# ================================================================ 3b. a script's question, the cold call, the repeat of a stored ask
from stackshot.service import question as _question_svc
from stackshot.service import writes as _writes
from stackshot.waits import handoff as _ho
setk(PREFIXES)
def post(ask, rid, options=None):
    body = {"project": "projects/alpha", "ask": ask, "text": "The settings layout is ready to pick.", "subject": f"[home] script question {rid}", "request_id": rid, "sender": "size-watch"}
    if options is not None: body["options"] = options
    return _question_svc._question("testbox", body)
def stored_ask(tag):
    for f in sorted((T / "store").glob("*/*.json")):
        d = json.loads(f.read_text())
        if tag in d.get("subject", ""): return d["metadata"].get("ask")
    return None
st, out = post(ask_with(LONG), "q1")
check("3b a script's question that links a listed page is filed, not refused", st == 200 and stored_ask("script question q1") == ask_with(LONG), (st, out))
st, out = post(ask_with(LONG), "q2", options=OPTS)
check("3b …with options too", st == 200 and stored_ask("script question q2") == ask_with(LONG), (st, out))
st, out = post(ask_with(LONG), "q3", options=opts_with(f"Ship it, see {LONG}."))
check("3b …but a link in an option is refused as in any write, with no word of a long page", st == 400 and "clickable card" in str(out) and "long page" not in str(out), (st, out))
st, out = post("not in the form " + LONG, "q4")
check("3b …and its ask is judged by its shape still: the shape refusal, not the link's", st == 400 and "Refused: ask must read" in str(out) and "long page" not in str(out), (st, out))
def with_question(f):
    """f run with the question flag on (the script routes set it around their own write); the flag is put back, and the run's error is read, never raised."""
    _writes.QUESTION.on = True
    try: return attempt(f)
    finally: _writes.QUESTION.on = False
out, err = with_question(lambda: mk(ask="", next=ask_with(LONG) + "\nOliver: answer the ask"))
check("3b the question flag: an ask the first line of next carries is taken as it is", bool(re.match(r"created \w\d+", str(out))) and "taken as the ask" in str(out), err or str(out)[:300])
item(9, needs=["decision"], ask=ASK, mover="Oliver", then="team-back")
_, err = with_question(lambda: upd(9, ask=ask_with(LONG)))
check("3b the question flag: an update that sets the ask is not judged either", rd(9)["metadata"]["ask"] == ask_with(LONG), err or rd(9)["metadata"])
refused("3b …and with the flag off the same write is refused", lambda: upd(9, ask=ask_with(LONG)), refusal(LONG))
item(13, needs=["decision"], ask=ASK, mover="Oliver", then="team-back")
_, err = with_question(lambda: upd(13, next=ask_with(LONG) + "\nOliver: answer the ask"))
check("3b the question flag: an ask the first line of next carries on an update is not judged either", rd(13)["metadata"]["ask"] == ask_with(LONG), err or rd(13)["metadata"])

# the cold call's own write: the server flags it (writes.cold_write, set by handoff_cold around its update calls, in a try/finally). A label a caller passes (the sender of the update tool) is no such flag.
COLD_KW = dict(needs=["decision"], ask=ask_with(LONG), options=OPTS, next=f"{OWNER}: answer the ask on the item", clear_next=True)
check("3b the cold call's flag is off outside its write", _writes.cold_ask() is False)
item(11, needs=["decision"], ask=ASK, mover="Oliver", then="team-back")
def cold_own():
    with _writes.cold_write():
        check("3b …and on inside it", _writes.cold_ask() is True)
        return upd(11, sender=_ho.COLD, **COLD_KW)
_, err = attempt(cold_own)
check("3b the cold call's own write of an ask that links a listed page is accepted, as the cold call", rd(11)["metadata"]["ask"] == ask_with(LONG) and len(rd(11)["metadata"].get("options") or []) == 2, err or rd(11)["metadata"])
check("3b …and the flag is off again after it", _writes.cold_ask() is False)
item(14, needs=["decision"], ask=ASK, mover="Oliver", then="team-back")
def cold_own_ask_in_next():
    with _writes.cold_write():
        return upd(14, sender=_ho.COLD, next=ask_with(LONG) + "\nOliver: answer the ask")
_, err = attempt(cold_own_ask_in_next)
check("3b the cold call's own write that carries the ask as the first line of next is accepted too", rd(14)["metadata"]["ask"] == ask_with(LONG), err or rd(14)["metadata"])
def cold_boom():
    with _writes.cold_write():
        raise RuntimeError("the write failed")
_, err = attempt(cold_boom)
check("3b the flag is off again after a write that raised (it is put back in a finally)", "the write failed" in err and _writes.cold_ask() is False, err)
with _writes.cold_write():
    with _writes.cold_write(): pass
    check("3b a write inside a write puts back what the outer one had", _writes.cold_ask() is True)
check("3b …and the outer one's end puts the flag off", _writes.cold_ask() is False)
item(12, needs=["decision"], ask=ASK, mover="Oliver", then="team-back")
refused_nw("3b a session that writes the same ask is refused", 12, lambda: upd(12, sender="team-back", ask=ask_with(LONG)), refusal(LONG))
refused_nw("3b …the flag is not left on: the same write as the cold call's label, with no flag, is refused", 12, lambda: upd(12, sender=_ho.COLD, **COLD_KW), refusal(LONG))
refused_nw("3b …and the same label with an option that holds a listed link, no flag, is refused for the long page", 12, lambda: upd(12, sender=_ho.COLD, options=opts_with(f"see {LONG}")), refusal(LONG, "option 1 (Approve)"))
def cold_option():
    with _writes.cold_write():
        return upd(12, sender=_ho.COLD, options=opts_with(f"see {LONG}"))
refused_nw("3b …with the flag on too: a link in an option is refused, with no word of a long page", 12, cold_option, "clickable card")

# the REAL tool entry point (stackshot_update, what an MCP caller reaches): a sender label is free text and exempts nothing. The same write the cold call makes, with its label, is refused
item(15, needs=["decision"], ask=ASK, mover="Oliver", then="team-back")
refused_nw("3b the update tool with sender cold-call and an ask that links a listed page is refused", 15, lambda: _wt_update.stackshot_update("a15", sender=_ho.COLD, **COLD_KW), refusal(LONG))
refused_nw("3b …the same with the label in another case or with spaces", 15, lambda: _wt_update.stackshot_update("a15", sender="  Cold-Call ", **COLD_KW), refusal(LONG))
refused_nw("3b …the ask as the first line of next, through the tool", 15, lambda: _wt_update.stackshot_update("a15", sender=_ho.COLD, next=ask_with(LONG) + "\nOliver: answer the ask"), refusal(LONG))
refused_nw("3b …a script label does not exempt it either", 15, lambda: _wt_update.stackshot_update("a15", sender="a script on testbox", **COLD_KW), refusal(LONG))
refused_nw("3b …nor a session's name", 15, lambda: _wt_update.stackshot_update("a15", sender="team-back", **COLD_KW), refusal(LONG))
refused_nw("3b …nor any other label the tool takes (owner, mover, then, agent) beside a session sender", 15, lambda: _wt_update.stackshot_update("a15", sender="team-back", owner=_ho.COLD, mover=_ho.COLD, then=_ho.COLD, **COLD_KW), refusal(LONG))
_, err = attempt(lambda: _wt_update.stackshot_update("a15", sender=_ho.COLD, ask=ask_with(SHORT)))
check("3b …while the tool takes a short decision page from any sender, as before", rd(15)["metadata"]["ask"] == ask_with(SHORT), err or rd(15)["metadata"])
check("3b the flag is off after all of these, in this thread", _writes.cold_ask() is False and _writes.question() is False)

# the repeat of a stored ask as the first line of next is no write of the ask; a changed one is
item(10, needs=["decision"], ask=ask_with(LONG), mover="Oliver", then="team-back")
upd(10, next=ask_with(LONG) + "\nOliver: answer the ask")
check("3b update: a stored ask that links a listed page, repeated as the first line of next, is no write of the ask: accepted, the ask as it was, the line out of next",
      rd(10)["metadata"]["ask"] == ask_with(LONG) and ask_with(LONG) not in str(rd(10)["metadata"].get("next")), rd(10)["metadata"])
refused_nw("3b update: …and the first line of next that changes the ask to another listed page is refused", 10, lambda: upd(10, next=ask_with(NOTES + "beta") + "\nOliver: answer the ask"), refusal(NOTES + "beta"))
check("3b update: …the stored ask is as it was", rd(10)["metadata"]["ask"] == ask_with(LONG), rd(10)["metadata"])
upd(10, next=ask_with(SHORT) + "\nOliver: answer the ask")
check("3b update: …and one that changes it to a short decision page is taken", rd(10)["metadata"]["ask"] == ask_with(SHORT), rd(10)["metadata"])
e = refusal(LONG, "option 1 (Approve)")
check("3b the refusal of an option says where the link goes and no longer says to link the page in the option", "the ask's Decide part" in e and "take the link out of the option" in e and "so link a short decision page" not in e, e)
check("3b the refusal of an ask keeps the words it had", "so link a short decision page made for this decision" in refusal(LONG) and "Decide part" not in refusal(LONG), refusal(LONG))
setk(KeyError)

# ================================================================ 3c. the defaults: a call that names no links argument judges links
setk(PREFIXES)
_, err = attempt(lambda: _asks._gate_ask(ask_with(LONG)))
check("3c _gate_ask with no links argument refuses a listed link", refusal(LONG) in err, err)
out, err = attempt(lambda: _asks._gate_ask(ask_with(SHORT)))
check("3c …and takes a short decision page", out == ask_with(SHORT), err or out)
out, err = attempt(lambda: _asks._gate_ask(ask_with(LONG), links=False))
check("3c …links=False leaves the link rule out (the shape still stands)", out == ask_with(LONG), err or out)
_, err = attempt(lambda: _wait_gates._gate_options(opts_with(f"see {LONG}")))
check("3c _gate_options with no links argument refuses a listed link, naming the option", refusal(LONG, "option 1 (Approve)") in err, err)
out, err = attempt(lambda: _wait_gates._gate_options(opts_with("Ship the new layout now.")))
check("3c …and takes options with no link", isinstance(out, list) and len(out) == 2, err or out)
_, err = attempt(lambda: _wait_gates._gate_options(opts_with(f"see {LONG}"), links=False))
check("3c …links=False leaves the long-page rule out: a link in an option is refused as any link is", "clickable card" in err and "long page" not in err, err)
setk(KeyError)

# ================================================================ 4. the text and the docs
snap = json.loads(pathlib.Path(STACK, "tests/tool_text.snapshot.json").read_text(encoding="utf-8"))["tools"]
for tool in ("create", "update"):
    d = json.dumps(snap[tool], ensure_ascii=False)
    check(f"4 text: {tool} says an ask's link is a short decision page, never a long project or notes page", "A link in the ask goes to a short decision page made for it (an artifact, a document or a mockup page), never a long project or notes page." in d, tool)
    check(f"4 text: {tool} says the instance may refuse such a link in an ask, and in an option, where the short link goes", "where the instance lists such pages, an ask that links one is refused when the write sets it, and so is an option that links one (an option holds no link: the short link goes in the ask's Decide part)" in d, tool)
doc = pathlib.Path(STACK, "docs/configuration.md").read_text(encoding="utf-8")
check("4 docs: the config key is in the configuration table", "`ask.refuse_link_prefixes` | `[]`" in doc)
check("4 docs: the key is in the example file with an empty list", re.search(r"(?m)^refuse_link_prefixes = \[\]", pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")) is not None)
docs_asks = pathlib.Path(STACK, "docs/asks-and-answers.md").read_text(encoding="utf-8")
check("4 docs: the asks page has the rule", "A decision's link is a short decision page" in docs_asks)
check("4 docs: …what is made equal and what is matched as written", "What is made equal:" in docs_asks and "What is matched as written" in docs_asks and "an escape written twice" in docs_asks and "the case of any other path" in docs_asks)
check("4 docs: …the text of a link read as an address, the option's refusal, and the scripts left out", "link text that is itself a listed address is refused" in docs_asks and "put a link to a short decision page in the ask's Decide part" in docs_asks
      and "A script's own question" in docs_asks and "the cold call's ask are not judged" in docs_asks)
check("4 docs: the configuration page says a script's question and the cold call's ask are not judged", "A script's own question and the cold call's ask are not judged." in doc)

check("4 docs: a user name before the host is ignored (made equal), no longer listed as matched as written", "a user name (and password) before the host (ignored)" in docs_asks and "an escape written twice (`%252F`), a user name" not in docs_asks)
check("4 docs: a prefix that ends with / is the folder and takes its own link without the slash", "a prefix that ends with `/` means the folder" in docs_asks and "(`.../projects/` takes `.../projects`)" in docs_asks
      and "also takes the folder's own link without the closing slash" in doc and "the folder's own link without the closing slash" in re.sub(r"\n\s*# ", " ", pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")))
check("4 docs: the known limits are listed, and the prefix is a guard, not a security boundary", all(w in docs_asks for w in ("a percent-encoded or fullwidth host", "`https:///host`", "`https:/host`", "`/raw/`, `/blame/` and `/edit/`", "a `.git` suffix", "in the order written", "never matches, because the link reader stops",
                                                                                                                  "on every host", "not a security boundary")) and "not a security boundary" in doc and "not a security boundary" in pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
check("4 docs: the cold call's ask is exempt by a flag the server sets, never by the sender label", "never read from a tool parameter" in docs_asks and "does not exempt an ask" in docs_asks)
setk(was) if had else setk(KeyError)
if was_mock is None: cfg_cl.pop("mockup_hosts", None)
else: cfg_cl["mockup_hosts"] = was_mock
import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": ask long-link scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
