"""Scenario test for the gate that keeps the item page's Yes / No fallback from being drawn under a question it cannot answer when the question is not phrased with an English question word
(server._gate_recommend_stance, ask_read.recommend_stance) — fixture data, no live store, no network, no server socket.

A needs=decision item with no options gets a bare Yes / No on the item page. The open-question gate reads the Decide part for an English question word, so a noun phrase or a question in another language
passed it and the page drew Yes / No under "who joins and which topic". The write check reads the Recommend part instead: with no options it must be a yes or a no, in any language (the English words ship;
other languages' words come from [keywords.ask_options] yes_no_words, here Greek stand-ins and the invented "vey").

  1  a create with no options is refused when the Recommend names a person, a topic or a date (a noun-phrase Decide, a Greek Decide, a yes/no Decide), or only starts with the letters of a yes/no word
     (Yesterday, Nothing, Go with Elena); the refusal quotes the Recommend, says the page would draw Yes / No, gives the options form and the yes/no way out; an English question word keeps its own refusal first
  2  accepted: a Recommend that opens with yes, no, approve, decline, go ahead, hold, okay, behind a quote or mark; with options listed (the Recommend naming a label); an item that is no decision
  3  the words come from configuration: a configured Greek yes passes only while it is configured (a live reload), a `particles` suffix may follow one, the English words keep working
  4  an update: a changed ask, options cleared, or a move to needs=decision with such a Recommend is refused; an item already stored this way is not refused for an unrelated write or a close
  5  the asks the server writes itself (the watchers' questions, the post-wake question) and the question route are not read
  6  the reading functions; 7 the tool text says it

    tests/run-suite decision_stance        → exit 0 / 1"""
import json, os, re, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="stance-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
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

DESC = "- Which layout the settings page gets\n- Done when the layout is picked"
tail = " · Stakes: low · By: Fri"
YN = "Decide: whether to ship the new layout · Recommend: yes" + tail            # a yes/no frame
OPEN = lambda decide, rec="Alpha": f"Decide: {decide} · Recommend: {rec}{tail}"
A = {"label": "Alpha", "line": "The wide layout.", "recommended": True}; B = {"label": "Beta", "line": "The narrow layout.", "recommended": False}
OPTS = [A, B]
WORDS = ("what", "which", "how", "who", "whom", "whose", "when", "where", "why")
PHRASES = {"what": "what to ship", "which": "which layout to ship", "how": "how the layout is shipped", "who": "who ships the layout", "whom": "whom to ask about the layout",
           "whose": "whose layout ships", "when": "when to ship the layout", "where": "where the layout ships", "why": "why the layout ships"}
assert set(PHRASES) == set(WORDS)


def item(i, status="open", desc=None, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] settings layout {i}", "description": desc or DESC, "status": status, "updated": now0 - 3 * H,
                                                      "state_updated": now0 - 3 * H, "confirmed": now0 - 3 * H,
                                                      "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "Oliver: answer the ask", **meta}}))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())
raw = lambda i: (T / f"store/a/{i}.json").read_text()
def count(): return len(list((T / "store/a").glob("*.json")))
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def err(f):
    try: return "", f()
    except Exception as e: return str(e), None
def refused(name, f, *want):
    e, out = err(f); check(name, bool(e) and all(w in e for w in want), e or out)
    return e
def refused_nw(name, i, f, *want):
    was = raw(i); e = refused(name, f, *want); check(name + " (nothing written)", raw(i) == was, None); return e
def refused_nc(name, f, *want):
    n = count(); e = refused(name, f, *want); check(name + " (nothing created)", count() == n, None); return e
def passes(name, f):
    e, out = err(f); check(name, not e, e); return out
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.waits import watchers as wk
server._publish = lambda: None
server._refuse_if_owing = lambda debtor: None
server._tell_woken = lambda *a, **k: None
upd = lambda i, sender="home-front", **kw: server._update(f"a{i}", sender=sender, **kw)
mk = lambda **kw: server._create(**{"subject": "[home] pick the settings layout", "description": DESC, "project": "projects/alpha", "owner": "home-front",
                                    "next": "Oliver: answer the ask", "needs": ["decision"], "ask": YN, **kw})

tail = " · Stakes: low · By: Fri"
ASK = lambda decide, rec: f"Decide: {decide} · Recommend: {rec}{tail}"
GUEST = "the guest and the topic for Friday"                       # a noun phrase: no English question word, so the open-question gate does not read it
GREEK_Q = "ποιος θα συμμετάσχει και ποιο θέμα"                      # "who joins and which topic", in a language the English question words do not cover
GREEK_YES, GREEK_NO = "ναι", "όχι"                                  # stand-in yes and no words of another language
E = {"label": "Elena on pricing", "line": "Elena joins and speaks on pricing.", "recommended": True}; N = {"label": "Nikos on safety", "line": "Nikos joins and speaks on safety.", "recommended": False}
OPTS = [E, N]
STANCE = ("Refused", "lists no options", "Recommend part", "is not a yes or a no", "Yes / No", "options=[", "exactly one recommended", "Decide: whether to", "Recommend part of yes or no", "cached tool list")
from stackshot.core import config as _cfg
def kw_set(words=(), particles=()):
    sec = _cfg.CFG.setdefault("keywords", {}).setdefault("ask_options", {}); sec["yes_no_words"] = list(words); sec["particles"] = list(particles)
def kw_off(): _cfg.CFG.get("keywords", {}).pop("ask_options", None)
kw_off()
stored = lambda out: bool(re.match(r"created \w\d+", out or ""))

try:
    # ================================================================ 1. a create: no options and a Recommend that is no yes or no is refused
    e = refused_nc("1 create: a noun-phrase Decide with a Recommend naming a person and a topic and no options is refused", lambda: mk(ask=ASK(GUEST, "Elena, on pricing")), *STANCE, "Elena, on pricing")
    check("1 create: the refusal quotes the Recommend part, says the page would draw only Yes / No, then gives the options form, then the yes/no way out",
          e.startswith("Refused: this needs=decision item lists no options and its Recommend part (“Elena, on pricing”) is not a yes or a no.") and e.index("Yes / No") < e.index("options=[") < e.index("Decide: whether to"), e)
    check("1 create: …and tells the agent to name the recommended option's label in the Recommend part", "name the recommended option's label in the ask's Recommend part" in e, e)
    refused_nc("1 create: a Decide in another language (Greek) with a Recommend naming a person and a topic is refused", lambda: mk(ask=ASK(GREEK_Q, "η Ελένη και το θέμα των τιμών")), *STANCE)
    refused_nc("1 create: a yes/no Decide with a Recommend that is a date is refused", lambda: mk(ask=ASK("whether the guest joins", "Friday at ten")), *STANCE)
    refused_nc("1 create: a Recommend that names a topic only is refused", lambda: mk(ask=ASK(GUEST, "pricing")), *STANCE)
    for rec in ("Yesterday", "Nothing yet", "Notion", "Go with Elena", "Hold the 12th", "Go to Berlin", "Ship it", "none, your call"):
        refused_nc(f"1 create: a Recommend of “{rec}” is no yes or no", lambda rec=rec: mk(ask=ASK("whether to ship the new layout", rec)), *STANCE[:4])
    e = refused_nc("1 create: options=\"none\" and an empty list are none", lambda: mk(ask=ASK(GUEST, "Elena"), options="none"), *STANCE[:4])
    refused_nc("1 create: …an empty options list too", lambda: mk(ask=ASK(GUEST, "Elena"), options=[]), *STANCE[:4])
    e = refused_nc("1 create: an English question word keeps its own refusal, which comes first", lambda: mk(ask=ASK("which guest joins on Friday", "Elena")), "Refused", "its Decide part is an open question")
    check("1 create: …and that refusal is not the Recommend one", "is not a yes or a no" not in e, e)

    # ================================================================ 2. a create: what is accepted
    for rec in ("yes", "No", "Yes, ship it", "NO - not this week", "Yes.", "Approve", "approved, go", "Decline", "Go ahead", "go ahead and ship", "Go.", "Hold - wait a week", "Hold", "Yep", "okay", "No-go",
                '"yes"', "“No”, not now", "(yes)", "**Yes**", "Reject it"):
        out = passes(f"2 create: a Recommend of “{rec}” is a yes or a no and passes with no options", lambda rec=rec: mk(ask=ASK(GUEST, rec)))
        check(f"2 create: …“{rec}” is stored", stored(out), out)
    out = passes("2 create: a yes/no Decide in Greek with a Recommend of yes passes", lambda: mk(ask=ASK(GREEK_Q, "yes")))
    check("2 create: …it is stored", stored(out), out)
    out = passes("2 create: options listed: the Recommend names a person and a topic, and it passes (it names the recommended label)", lambda: mk(ask=ASK(GUEST, "Elena on pricing"), options=OPTS))
    check("2 create: …stored, and no note (the label is named)", stored(out) and "(note:" not in (out or ""), out)
    out = passes("2 create: options listed with a Recommend that is no stance and names no label is the note's business (never a refusal here)", lambda: mk(ask=ASK(GUEST, "Elena"), options=OPTS))
    check("2 create: …stored with the note", stored(out) and "(note: the ask's Recommend part does not name the recommended option" in (out or ""), out)
    passes("2 create: an item that is no decision is not read", lambda: server._create(subject="[home] build the guest list", description=DESC, project="projects/alpha", owner="home-front",
                                                                                          next="team-back: build it", needs=["team-back"], ask=ASK(GUEST, "Elena")))

    # ================================================================ 3. the words come from configuration
    refused_nc("3 config: with nothing configured a Greek yes is no yes or no (only the English words ship)", lambda: mk(ask=ASK(GUEST, GREEK_YES + ", προχωράμε")), *STANCE[:4])
    kw_set(words=[GREEK_YES, GREEK_NO])
    out = passes("3 config: the configured Greek yes passes", lambda: mk(ask=ASK(GUEST, GREEK_YES + ", προχωράμε")))
    check("3 config: …stored", stored(out), out)
    passes("3 config: …the configured Greek no, in capitals with a mark, passes", lambda: mk(ask=ASK(GUEST, GREEK_NO.upper() + "! όχι τώρα")))
    passes("3 config: …the English words still pass beside them", lambda: mk(ask=ASK(GUEST, "Yes")))
    refused_nc("3 config: …a Greek name is still refused", lambda: mk(ask=ASK(GREEK_Q, "η Ελένη")), *STANCE[:4])
    refused_nc("3 config: …and a word that only starts with a configured one is refused", lambda: mk(ask=ASK(GUEST, GREEK_YES + "φ")), *STANCE[:4])
    kw_set(words=["vey"], particles=["zz"])
    passes("3 config: a `particles` suffix may follow a configured word", lambda: mk(ask=ASK(GUEST, "veyzz, do it")))
    refused_nc("3 config: …a suffix that is not one is no yes", lambda: mk(ask=ASK(GUEST, "veyq")), *STANCE[:4])
    kw_off()
    refused_nc("3 config: with the words removed again (a live reload) the same Recommend is refused", lambda: mk(ask=ASK(GUEST, "vey")), *STANCE[:4])

    # ================================================================ 4. an update
    item(1, needs=["decision"], ask=ASK("whether the guest joins", "yes"), mover="Oliver", then="team-back")
    refused_nw("4 update: a changed ask whose Recommend names a person, with no options listed, is refused", 1, lambda: upd(1, ask=ASK(GUEST, "Elena, on pricing")), *STANCE)
    refused_nw("4 update: …in Greek too", 1, lambda: upd(1, ask=ASK(GREEK_Q, "η Ελένη και το θέμα των τιμών")), *STANCE[:4])
    upd(1, ask=ASK(GUEST, "Elena on pricing"), options=OPTS)
    check("4 update: the same ask with its options in the same call is accepted", rd(1)["metadata"]["options"] == OPTS and rd(1)["metadata"]["ask"] == ASK(GUEST, "Elena on pricing"), rd(1)["metadata"])
    refused_nw("4 update: options=\"none\" under that ask is refused (the Recommend would be left to a Yes / No)", 1, lambda: upd(1, options="none"), *STANCE[:4])
    refused_nw("4 update: …so is clear_options=true", 1, lambda: upd(1, clear_options=True), *STANCE[:4])
    upd(1, ask=ASK("whether the guest joins", "no"), options="none")
    check("4 update: options=\"none\" with a yes/no ask in the same call is accepted", "options" not in rd(1)["metadata"] and rd(1)["metadata"]["ask"] == ASK("whether the guest joins", "no"), rd(1)["metadata"])
    item(3, needs=["team-back"], ask=ASK(GUEST, "Elena, on pricing"), next="team-back: build it", mover="team-back")
    refused_nw("4 update: a move to needs=decision with a Recommend that is no yes or no and no options is refused", 3, lambda: upd(3, needs=["decision"], mover="Oliver", then="team-back"), *STANCE[:4])
    upd(3, needs=["decision"], options=OPTS, mover="Oliver", then="team-back")
    check("4 update: …accepted with the options in the same call", rd(3)["metadata"]["needs"] == ["decision"] and rd(3)["metadata"]["options"] == OPTS, rd(3)["metadata"])
    # an item already stored this way is not refused for an unrelated write, nor is its close
    item(5, needs=["decision"], ask=ASK(GUEST, "Elena, on pricing"), mover="Oliver", then="team-back", state="your-call")
    was = rd(5)["metadata"]["ask"]
    upd(5, priority="p3")
    check("4 update: a priority on an item stored with such an ask is not refused", rd(5)["metadata"]["priority"] == "p3" and rd(5)["metadata"]["ask"] == was, rd(5)["metadata"])
    upd(5, description="- Who joins on Friday and on what topic, said again\n- Done when it is picked")
    check("4 update: …nor a description", "said again" in rd(5)["description"], rd(5)["description"])
    upd(5, next="Oliver: answer the ask on the item")
    check("4 update: …nor a next", rd(5)["metadata"]["next"].startswith("Oliver: answer"), rd(5)["metadata"].get("next"))
    upd(5, needs=["decision"])
    check("4 update: …nor the same needs sent again", rd(5)["metadata"]["needs"] == ["decision"], rd(5)["metadata"])
    passes("4 update: …nor a close", lambda: upd(5, status="completed", outcome="done", reason="Elena joins on pricing, said in a call", outcome_text="- Elena joins on pricing"))
    item(6, needs=["team-back"], ask=ASK(GUEST, "Elena"), next="team-back: build it", mover="team-back")
    passes("4 update: an item that is no decision may carry such an ask", lambda: upd(6, priority="p2"))

    # ================================================================ 5. the asks the server writes itself and the question route
    ev = {"wait_event": "countersigned NDA"}
    for what, ask, opts in (("the relay question", wk.relay_ask(ev), wk.relay_options()), ("the drop question", wk.drop_ask(ev), wk.drop_options())):
        m = {"needs": ["decision"], "ask": ask, "options": opts, "watch": {"asked": "relay" if "relay" in what else "dropit"}}
        passes(f"5 watcher: {what} passes the Recommend gate", lambda m=m: server._gate_recommend_stance(m))
        m2 = {**m, "options": None}
        passes(f"5 watcher: {what} without its options is still the watcher's own and passes", lambda m2=m2: server._gate_recommend_stance(m2))
    ask, opts = server._watch_ask("a1", {}, "its wait ended")
    passes("5 post-wake: the question the server builds (two options) passes", lambda: server._gate_recommend_stance({"needs": ["decision"], "ask": ask, "options": opts}))
    server._QUESTION.on = True
    try:
        out = passes("5 question route: a script's question with a Recommend that is no yes or no still files an item", lambda: mk(ask=ASK(GUEST, "none, your call")))
    finally:
        server._QUESTION.on = False
    check("5 question route: …it is stored", stored(out), out)
    refused_nc("5 question route: …while the same ask through the create tool is refused", lambda: mk(ask=ASK(GUEST, "none, your call")), *STANCE[:4])

    # ================================================================ 6. the reading functions
    from stackshot.model import ask_read as ar
    check("6 recommend_stance: English words open it; a word that only starts with one does not",
          all(ar.recommend_stance(x) for x in ("yes", "No.", "Approve it", "go ahead")) and not any(ar.recommend_stance(x) for x in ("Yesterday", "Nothing", "Go with Elena", "Elena", "")), "")
    check("6 recommend_not_stance: the Recommend text when there are no options and it is no stance; \"\" with options, with a stance, with no ask in form",
          ar.recommend_not_stance({"ask": ASK(GUEST, "Elena")}) == "Elena" and ar.recommend_not_stance({"ask": ASK(GUEST, "Elena"), "options": OPTS}) == ""
          and ar.recommend_not_stance({"ask": ASK(GUEST, "yes")}) == "" and ar.recommend_not_stance({"ask": "which guest? Elena"}) == "" and ar.recommend_not_stance({}) == "", "")

    # ================================================================ 7. the tool text
    snap = json.loads(pathlib.Path(STACK, "tests/tool_text.snapshot.json").read_text(encoding="utf-8"))["tools"]
    for tool in ("create", "update"):
        d = snap[tool]["description"]
        check(f"7 text: {tool} says a decision with no options whose Recommend is no yes or no is refused, and the two ways out",
              "whose Recommend part is not a yes or a no" in d and "put the choices as options, or make it a yes/no question with a Recommend of yes or no" in d, d[:200])
finally:
    kw_off()
    import shutil; shutil.rmtree(tmp, ignore_errors=True)      # the folder goes pass or fail
print(("ok" if not fails else "FAILED") + f": decision stance scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
