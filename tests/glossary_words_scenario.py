"""Scenario test for the save-time glossary: a retired role word in an item's subject or description is rewritten to its glossary term (create and update) — fixture data, no live store, no network.

The word list is a glossary JSON the config points at ([glossary] terms); the test writes its own copy in the scratch folder, so it reads no file of another repo. Hangul is written with chr().
Covers:

  1  module   glossary_words: a one-term word is rewritten and reported; a many-term word is never guessed and never refused; the exempt cases (the allowed person-word, quotes, backticks, a code block, a link target,
              a quote line) are untouched; no match is untouched; no file, a broken file and an unset path are no-ops; ask_writer_when_unclear false leaves a many-term word as written, with no line
  2  many     a many-term word is saved as written and the reply line names the word and its terms, in English for an English text and in the second language's catalog for a Hangul text; no refusal, no memory of a text
  3  create   through the MCP layer: the stored subject and description are the rewritten ones and the reply has the glossary line; an unclear word is stored as written with the reply line; exempt words are stored as written
  4  update   the same for update's subject and description; a write that passes neither is untouched, an old word already stored stays
  5  text     the create and update descriptions carry the glossary piece

    tests/run-suite glossary_words        -> exit 0 / 1"""
import asyncio, json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="glossw-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1   # never the host's transcripts
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
toml, n = re.subn(r'(?m)^terms = ""', f'terms = "{tmp}/terms.json"', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "brain/projects", "transcripts/-srv-x", "secrets"): (T / d).mkdir(parents=True)
NAMES = ("home-owner", "home-stew", "team-back", "home-front", "home-other")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a"} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-stew", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-other": "the other"},
                                                                                "back_agents": {"team-back": "the back", "home-other": "the other"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-other: the other\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- Goal: a thing works\n- It lives here\n- Done when done"
def item(i, subject):
    su = now0 - 10 * DAY
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject, "description": DESC, "status": "open", "updated": su, "state_updated": su, "confirmed": su,
                                                      "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "team-back: do the thing", "needs": ["team-back"], "mover": "team-back"}}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
def stored(): return [json.loads(p.read_text()) for p in (T / "store").glob("*/[0-9s]*.json")]
def made(subject): return [v for v in stored() if v.get("subject") == subject]
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server
from stackshot.web.tools import anchors as _wt_anchors, route as _wt_route
from stackshot.model import glossary_words as G
from stackshot.web import glossary_line as GL
from stackshot.web import publish as _web_publish, page_debts as _web_page_debts
from stackshot.service import telling
from fastmcp import Client
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
telling.tell_woken = lambda gid, owner, note, tag="wake": None
(T / "state/waiting.json").write_text(json.dumps({"baseline": now0 - 100 * DAY, "seen": {}, "reported": []}))
async def _call(name, args):
    async with Client(server.mcp) as c:
        r = await c.session.call_tool(name, args)
        return bool(r.is_error), "".join(getattr(x, "text", "") for x in r.content)
def call(name, **args): return asyncio.run(_call(name, args))
def upd(i, **kw): return call("update", item_id=f"a{i}", sender="home-front", **kw)
def mk(subject, description=DESC): return call("create", subject=subject, description=description, project="projects/alpha", sender="home-front", mover="team-back", next="team-back: go")

DAM = chr(0xB2F4) + chr(0xB2F9)                      # the retired word that stood for five roles
DAMJA = DAM + chr(0xC790)                            # the person-word that stays allowed
BUILDER_KO = chr(0xBE4C) + chr(0xB354)               # a word with one term
OWNER_KO = chr(0xC624) + chr(0xB108)                 # a word with two terms
USE = ["mover", "keeper", "contact", "front agent", "lead", "builder"]
TERMS = {"version": 1, "ask_writer_when_unclear": True, "avoid": [
    {"word": DAM, "regex": DAM + "(?!" + chr(0xC790) + ")", "hook": True, "use": USE, "note": ""},
    {"word": OWNER_KO, "regex": OWNER_KO, "hook": True, "use": ["mover", "keeper"], "note": ""},
    {"word": BUILDER_KO, "regex": BUILDER_KO, "hook": True, "use": ["builder"], "note": ""},
    {"word": "owner", "regex": None, "hook": False, "use": ["mover", "creator"], "note": ""},
    {"word": "maintainer", "regex": None, "hook": False, "use": ["builder"], "note": ""}]}
TP = T / "terms.json"; TP.write_text(json.dumps(TERMS), encoding="utf-8")

# ================================================================ 1 module
ents, ask = G.entries(str(TP))
check("module: only the hook entries with a regex are read (three of five), with the ask flag", [e["word"] for e in ents] == [DAM, OWNER_KO, BUILDER_KO] and ask is True, [e["word"] for e in ents])
rw = lambda t, a=True: G.rewrite(t, ents, a)
out, did, unc = rw(f"- the {BUILDER_KO} ships it")
check("module: a one-term word is rewritten to its term and reported", out == "- the builder ships it" and did == [(BUILDER_KO, "builder")] and not unc, (out, did, unc))
out, did, unc = rw(f"{BUILDER_KO} and {BUILDER_KO}")
check("module: every match of a word is rewritten", out == "builder and builder", out)
out, did, unc = rw(f"- {DAM} of the item")
check("module: a many-term word is not rewritten and is asked about with its terms", out == f"- {DAM} of the item" and not did and unc == [(DAM, USE)], (out, unc))
out, did, unc = rw(f"- {DAM} of the item", False)
check("module: ask_writer_when_unclear false leaves a many-term word as written, with no line and asks nothing", out == f"- {DAM} of the item" and not did and not unc, (out, unc))
for name, text in (("the allowed person-word", f"- ask the {DAMJA} here"), ("double quotes", f'- the word "{DAM}" is retired'), ("backticks", f"- the word `{DAM}` is retired"),
                   ("a code block", f"- see:\n```\n{DAM} {BUILDER_KO}\n```"), ("a link target", f"- [x](https://example.com/{BUILDER_KO}) here"), ("a quote line", f"> {BUILDER_KO} said so\n- fine"),
                   ("curly quotes", f"- the word “{BUILDER_KO}” is retired"), ("no match", "- nothing retired here")):
    out, did, unc = rw(text)
    check(f"module: {name} is untouched", out == text and not did and not unc, (out, did, unc))
out, did, unc = rw(f'- "{BUILDER_KO}" is quoted but {BUILDER_KO} is not')
check("module: a quoted match stays, an unquoted one in the same text is rewritten", out == f'- "{BUILDER_KO}" is quoted but builder is not', out)
check("module: apply with an unset path or a missing file is a no-op", GL.apply(f"s {BUILDER_KO}", "d", path="") == (f"s {BUILDER_KO}", "d", "")
      and GL.apply(f"s {BUILDER_KO}", "d", path=str(T / "none.json")) == (f"s {BUILDER_KO}", "d", ""), None)
(T / "bad.json").write_text("{not json", encoding="utf-8")
check("module: a file that is not JSON is a no-op too, never a refusal", GL.apply(f"s {DAM}", "d", path=str(T / "bad.json")) == (f"s {DAM}", "d", ""), None)
s, d, note = GL.apply(f"[home] the {BUILDER_KO}", f"- the {BUILDER_KO}", path=str(TP))
check("module: apply rewrites both fields and the line names the word and its term", s == "[home] the builder" and d == "- the builder" and note.startswith("\n(glossary:") and f"{BUILDER_KO} -> builder" in note, (s, d, note))
check("module: apply with nothing passed is untouched", GL.apply("", "", path=str(TP)) == ("", "", ""), None)

# ================================================================ 2 many
s, d, note = GL.apply(f"[home] {DAM} of x", "- plain", path=str(TP))
check("many: the text is saved as written and the line names the word and every term", s == f"[home] {DAM} of x" and d == "- plain" and note.startswith("\nglossary:") and DAM in note and "in the subject" in note
      and "mover, keeper, contact, front agent, lead or builder" in note and note.endswith("use the exact term next time"), note)
check("many: the same text sent again is answered the same way, nothing is remembered", GL.apply(f"[home] {DAM} of x", "- plain", path=str(TP)) == (s, d, note), None)
check("many: a text with a term in its place has no line", GL.apply("[home] mover of x", "- plain", path=str(TP)) == ("[home] mover of x", "- plain", ""), None)
s, d, note = GL.apply("[home] plain", f"- {DAM} here", path=str(TP))
check("many: a word in the description only says so", "in the description" in note and d == f"- {DAM} here", note)
s, d, note = GL.apply(f"[home] {DAM}", f"- {DAM} here", path=str(TP))
check("many: a word in both fields gets one line, not two", "subject and description" in note and note.count("glossary:") == 1, note)
s, d, note = GL.apply(f"[home] {DAM} of z", f"- {OWNER_KO} too", path=str(TP))
check("many: two unclear words get one line with both", note.count("glossary:") == 2 and "\n" not in note[1:] and "keeper" in note and "mover or keeper" in note, note)
s, d, note = GL.apply(f"[home] {BUILDER_KO} {DAM}", "- d", path=str(TP))
check("many: a one-term word beside a many-term word is rewritten and the other named", s.startswith("[home] builder ") and DAM in s and "(glossary: rewrote" in note and "could mean" in note, (s, note))
TA = dict(TERMS, avoid=[dict(TERMS["avoid"][0], word="owner-word", regex="ownerword")]); (T / "ascii.json").write_text(json.dumps(TA), encoding="utf-8")
s, d, note = GL.apply("[home] the ownerword", "- d", path=str(T / "ascii.json"))
check("many: an English text gets the English line", s == "[home] the ownerword" and note.startswith('\nglossary: "owner-word" in the subject could mean mover'), note)
TA2 = dict(TERMS, ask_writer_when_unclear=False); (T / "noask.json").write_text(json.dumps(TA2), encoding="utf-8")
check("many: ask_writer_when_unclear false gives no line", GL.apply(f"[home] {DAM}", "- d", path=str(T / "noask.json")) == (f"[home] {DAM}", "- d", ""), None)
# a second-language catalog is used for a Hangul text (an ASCII test locale)
from stackshot.web import i18n
(T / "loc").mkdir(); (T / "loc/ko.json").write_text(json.dumps({"glossary.unclear": "KO {word}/{where}/{terms}", "glossary.in.subject": "S", "glossary.or": " + "}), encoding="utf-8")
from stackshot.core import config as _cfg
_cfg.CFG.setdefault("ui", {})["locale_dir"] = str(T / "loc")
s, d, note = GL.apply(f"[home] {DAM}", "- d", path=str(TP))
check("many: a Hangul text takes the second language's line from the catalog", note == f"\nKO {DAM}/S/mover, keeper, contact, front agent, lead, + builder"[:0] + "\nKO " + DAM + "/S/mover, keeper, contact, front agent, lead + builder", note)
_cfg.CFG["ui"].pop("locale_dir", None)

# ================================================================ 3 create
err, text = mk(f"[home] Ship the {BUILDER_KO} fix", f"- Goal: the {BUILDER_KO} fix\n- It lives here\n- Done when done")
rows = made("[home] Ship the builder fix")
check("create: the stored subject and description carry the term and the reply has the glossary line", not err and len(rows) == 1 and rows[0]["description"].startswith("- Goal: the builder fix") and f"{BUILDER_KO} -> builder" in text and "(glossary:" in text, (err, text))
before = len(stored())
err, text = mk(f"[home] {DAM} of the export")
check("create: an unclear word is stored as written and the reply has the line naming its terms", not err and len(stored()) == before + 1 and len(made(f"[home] {DAM} of the export")) == 1 and "glossary:" in text and "could mean mover" in text, text)
err, text = mk("[home] mover of the export")
check("create: a text with a term has no glossary line", not err and "glossary:" not in text and len(made("[home] mover of the export")) == 1, text)
err, text = mk(f'[home] the word "{DAM}" in a quote', f"- Goal: `{DAM}` stays\n- It lives here\n- Done when done")
check("create: a retired word in quotes or backticks is stored as written, with no line", not err and "(glossary:" not in text and len(made(f'[home] the word "{DAM}" in a quote')) == 1, text)
err, text = mk(f"[home] ask the {DAMJA} about it")
check("create: the allowed person-word is stored as written", not err and "(glossary:" not in text and len(made(f"[home] ask the {DAMJA} about it")) == 1, text)

# ================================================================ 4 update
item(5, f"[home] old {DAM} subject")
err, text = upd(5, priority="p2")
check("update: a write that passes neither field leaves the stored old word alone, no line, no ask", not err and "(glossary:" not in text and rd(5)["subject"] == f"[home] old {DAM} subject", text)
err, text = upd(5, description=f"- Goal: the {BUILDER_KO} fix\n- It lives here\n- Done when done")
check("update: the description is stored rewritten and the reply says so", not err and rd(5)["description"].startswith("- Goal: the builder fix") and f"{BUILDER_KO} -> builder" in text, text)
err, text = upd(5, subject=f"[home] new {BUILDER_KO} subject")
check("update: the subject is stored rewritten", not err and rd(5)["subject"] == "[home] new builder subject" and "(glossary:" in text, (err, text, rd(5)["subject"]))
err, text = upd(5, subject=f"[home] new {DAM} subject")
check("update: an unclear word in the subject is stored as written and the reply names its terms", not err and rd(5)["subject"] == f"[home] new {DAM} subject" and "could mean mover" in text, (err, text))
err, text = upd(5, subject="[home] new keeper subject")
check("update: a text with a term goes through", not err and rd(5)["subject"] == "[home] new keeper subject", text)

# ================================================================ 5 text
tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
for name in ("create", "update"):
    d = " ".join(tools[name].description.split())
    check(f"text: the {name} description carries the glossary line", "rewritten to its glossary term" in d and "saved as written" in d and "refused" in d, d[-300:])

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": glossary words scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
