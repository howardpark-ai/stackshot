"""Scenario test for the audit's ask-options check (audit_checks.check_ask_options through filing_findings and audit_run.filing_pass): an open item's ask the page cannot be answered from. Fixture items,
messages replaced by recorders, no live store, no network, no model call.

An open question ("which layout …") on an item that lists no options gets a bare Yes / No on the item page, which cannot answer it, and a Recommend that answers a different question reads as a mistake. The write gates
refuse such an ask now; this finds the ones written before them, or that got through (a Yes / No pair stored under an open Decide, a Recommend that does not match the options).

  1  found: an old ask still showing Yes / No on an open question (no options; a Yes / No pair stored; an Approve / Decline pair stored), an ask that names alternatives with no option listed; the detail says
     what the page shows, the fix is the one line that tells the mover to rewrite the ask with options
  2  found: a Recommend part that does not match, with options (it does not name the recommended one; it names another) and with Yes / No under an open Decide (it answers yes or no)
  3  not found: a yes/no Decide with a matching Recommend (no options; a Yes / No pair), an open question that lists its options with a Recommend naming the recommended one, a Decide that holds "what" only later,
     an item that needs no decision, a watcher's own ask, a closed item, an item with no ask (ask-missing's), and the same words in the description only
  3b a Recommend that names its option by label (any case, trailing punctuation), letter, number, place ("the second") or leading word, or says there is no pick, is no mismatch; one that plainly names another
     option, or none by any form, is; with two options (drawn without letters) any place counts
  3b2 a leading word shared with another option's label does not pass the recommended one ("Ship later" for "Ship now"); an option, letter or place right after not, avoid, never, skip, except or instead of is turned away
     ("Wide, not Narrow" names Wide)
  3c options the page cannot read (one option, no single recommended, a non-boolean recommended) count as Yes / No, so an open question over them is found and the detail says so
  3d an ask that cannot be split into Decide and Recommend is not read
  4  the pass: the finding is a filing-pass finding, sent once to where the daily run's findings go (the project's -main agent, marked for the owner, for the owner's own item) with the fix line; sent again after a write
     only while it stands; quiet once the ask is rewritten with options (no message, gone from the record); the check is the write gates' own matchers (the server's names are ask_read's)

    tests/run-suite ask_options_audit        → exit 0 / 1"""
import json, os, pathlib, re, sys, time, unicodedata

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="askopts-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))

toml = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1
for key, val in (("agent", "falcon-audit"), ("builder", "falcon-engineer"), ("main", "falcon-main")):
    toml, n = re.subn(rf"(?m)^{key} = \"my-[a-z]+\"", f"{key} = \"{val}\"", toml); assert n == 1, key
toml, n = re.subn(r'(?m)^(\[audit\][^\n]*\n)enabled = false', r'\g<1>enabled = true', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "home/.claude/sessions").mkdir(parents=True)                                              # an isolated HOME: the pane registry is a folder of ours
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", HOME=str(T / "home"), STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "brain/projects", "fleet/a", "state"): (T / d).mkdir(parents=True)
(T / "store/anchors.json").write_text("{}"); (T / "store/projects.json").write_text(json.dumps({"pages": {}})); (T / "store/next-id").write_text("1")
(T / "fleet/a/sessions.json").write_text("{}"); (T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))

import audit_checks as AC, audit_run as AR, ask_read
H = 3600; now = time.time()
OWNER = "00000000-0000-4000-8000-000000000001"
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

def item(i, status="open", wrote=None, description="- A thing, finished when it works", **meta):
    wrote = now - H if wrote is None else wrote
    d = {"id": str(i), "subject": f"[home] item a{i}", "description": description, "status": status, "updated": wrote, "state_updated": wrote, "confirmed": wrote,
         "written_at": wrote, "written_by": "home-agent", "metadata": {"owner": OWNER, "project": "projects/alpha", **meta}}
    return f"a{i}", d
def asking(i, ask, options=None, **kw):
    """An item that needs the owner's decision (his move, as the audit sees it)."""
    return item(i, state="your-call", needs=["decision"], mover="Oliver", ask=ask, next="Oliver: decide", **({"options": options} if options else {}), **kw)
def ask(decide, rec, stakes="a day either way", by="no date"): return f"Decide: {decide} · Recommend: {rec} · Stakes: {stakes} · By: {by}"
def opts(*labels, rec=None):
    rec = labels[0] if rec is None else rec
    return [{"label": l, "line": f"Go with {l}.", "recommended": l == rec} for l in labels]
def build(*pairs): return dict(pairs)
ROLES = {"home-agent": {"role": "background"}, "alpha-main": {"role": "front"}, "alpha-builder": {"role": "background"}}
sent = []
def deliver(to, text, fyi=False): sent.append((to, text, fyi)); return True, "[200] ok"
def env(**kw):
    kw.setdefault("pages", lambda run, deadline: {"enabled": False, "mode": "", "counts": {}})
    return AR.Env(roles=ROLES, fallback=lambda p: "alpha-main", builder=lambda p: "alpha-builder", page_of=lambda p: ("", None), deliver=kw.pop("deliver", deliver), sessions=lambda: None, **kw)
def clear_state():
    for p in (T / "state/audit").glob("*.json"): p.unlink()
    sent.clear()
def found(items):
    fs, _flags = AC.filing_findings(items, {}, now, env())
    return {f["id"]: f for f in fs if f["category"] == "ask-options"}, fs

OPEN = ask("which layout the item page uses", "the narrow one")
YESNO = ask("whether to ship the retry change", "ship")
ALT = ask("the side panel's left line: A (full height, as now) or B (starts below the cards)", "A")
OPT_PAIR = [{"label": "Yes", "line": "Answer yes.", "recommended": True}, {"label": "No", "line": "Answer no.", "recommended": False}]
GO_PAIR = [{"label": "Approve", "line": "Go ahead.", "recommended": True}, {"label": "Decline", "line": "Hold it.", "recommended": False}]

# ---- 1. found: Yes / No under a question it cannot answer
cases = build(
    asking(1, OPEN),                                                           # the old ask: an open question, no options, so the page draws Yes / No
    asking(2, ask("how the nightly run should retry", "three tries"), OPT_PAIR),   # a Yes / No pair stored under an open question
    asking(3, ask("what to do about the stale cache", "drop it"), GO_PAIR),        # an Approve / Decline pair under one
    asking(4, ALT),                                                            # alternatives named, none listed
    asking(5, ask("“when” to cut the release", "friday")),                      # a quote does not hide the opening word
)
got, _all = found(cases)
check("1 an old ask still on Yes / No under an open question is found, with what the page shows", set(got) == {"board#1", "board#2", "board#3", "board#4", "board#5"}
      and "open question" in got["board#1"]["detail"] and "only Yes / No under it" in got["board#1"]["detail"], got)
check("1 …a stored Yes / No pair, and an Approve / Decline pair, count as the same buttons", "only Yes / No" in got["board#2"]["detail"] and "only Yes / No" in got["board#3"]["detail"], (got["board#2"], got["board#3"]))
check("1 …alternatives with no option listed are found as such", "names alternatives" in got["board#4"]["detail"] and "lists no options" in got["board#4"]["detail"], got["board#4"])
f1 = got["board#1"]
check("1 the finding has the audit's shape: project, mover, category, source code, and the fix is the one line to rewrite the ask with options",
      f1["project"] == "projects/alpha" and f1["mover"] == "Oliver" and f1["source"] == "code" and f1["fix"] == AC.FIX["ask-options"] and "rewrite the ask with options" in f1["fix"]
      and "\n" not in f1["fix"] and "2 to 6" in f1["fix"], f1)
check("1 the category is one the filing pass can raise, with a fix line", "ask-options" in AC.CHECKS_FILING and AC.FIX.get("ask-options"))

# ---- 2. found: a Recommend that does not match
miss = build(
    asking(9013, ask("which layout the item page uses", "Beta"), opts("Alpha", "Beta", "Gamma", rec="Gamma")),      # options listed; the Recommend names another option, not the recommended one
    asking(9082, ask("which layout the item page uses", "the slim one"), opts("Wide", "Narrow")),                  # the Recommend names none of the options
    asking(9071, ask("which layout the item page uses", "yes")),                                                    # no options, open Decide, Recommend answers yes
    asking(9011, ask("which layout the item page uses", "No, keep it"), OPT_PAIR),
)
got, _all = found(miss)
check("2 options listed and the Recommend names another option: found, naming both", "board#9013" in got and "does not name the recommended option ('Gamma')" in got["board#9013"]["detail"]
      and "names another ('Beta')" in got["board#9013"]["detail"] and "Yes / No" not in got["board#9013"]["detail"], got.get("board#9013"))
check("2 options listed and the Recommend names none: found", "board#9082" in got and "does not name the recommended option ('Wide')" in got["board#9082"]["detail"] and "names another" not in got["board#9082"]["detail"], got.get("board#9082"))
check("2 Yes / No under an open Decide whose Recommend answers yes: both halves in one finding", "board#9071" in got and "open question" in got["board#9071"]["detail"]
      and "answers yes or no to a question that is not a yes/no" in got["board#9071"]["detail"] and got["board#9071"]["detail"].count("; ") == 1, got.get("board#9071"))
check("2 …a stored Yes / No pair under an open Decide whose Recommend opens with no: the buttons and the yes/no answer, in one finding",
      "board#9011" in got and "only Yes / No under it" in got["board#9011"]["detail"] and "answers yes or no to a question that is not a yes/no" in got["board#9011"]["detail"], got.get("board#9011"))

# ---- 3. not found
fine = build(
    asking(20, YESNO),                                                                     # a yes/no Decide, a Recommend that answers it, the page's Yes / No
    asking(21, YESNO, OPT_PAIR),                                                           # …with the pair stored
    asking(22, ask("whether to ship the retry change", "yes, ship it")),                    # "yes" in a Recommend that answers a yes/no
    asking(23, ask("which layout the item page uses", "Narrow, the one that fits a phone"), opts("Wide", "Narrow", rec="Narrow")),      # an open question that lists its answers, Recommend names the recommended one
    asking(24, ask("whether what we shipped is enough", "yes")),                              # "what" only later in a yes/no frame
    asking(25, ask("should we ship A or hold", "ship")),                                      # a "should" frame passes the read the write gates use
    item(26, state="doing", needs=["home-agent"], ask=OPEN, mover="home-agent", next="home-agent: build it"),      # needs no decision
    item(27, state="your-call", needs=["decision"], mover="Oliver", ask="Decide: when does the vendor reply arrive? · Options: arrived / not yet, ask again on <date> / drop", next="Oliver: decide", watch={"asked": "relay"}),      # a watcher's own ask
    asking(28, OPEN, status="completed", outcome="done"),                                     # closed
    item(29, state="your-call", needs=["decision"], mover="Oliver", next="Oliver: decide"),    # no ask at all: ask-missing's
    asking(30, YESNO, description="- Which of the two options is better?\n- Option A or option B"),   # the same words in the description only
)
got, allf = found(fine)
check("2/3 a yes/no with a matching Recommend (no options, a stored pair, a Recommend that opens with yes), an open question that lists its options, a Decide holding 'what' only later,"
      " a 'should' frame, an item that needs no decision, a watcher's ask, a closed item, no ask and a description alone are none a finding", set(got) == set(), got)
mm = ask_read.recommend_missing({"ask": ask("which", "Beta"), "options": opts("Alpha", "Beta", rec="Alpha")})
check("3 the matcher is the write gates': the server's names are ask_read's own", mm == "Alpha", mm)
import server
check("3 …server._open_question, _recommend_missing, _alternatives and _yes_no_options are ask_read's functions", server._open_question is ask_read.open_question and server._recommend_missing is ask_read.recommend_missing
      and server._alternatives is ask_read.alternatives and server._yes_no_options is ask_read.yes_no_options and server._lettered_alternatives is ask_read.lettered_alternatives)

# ---- 3b. a Recommend that names its option in another form is no mismatch
LAYOUT = lambda rec, o: asking(0, ask("which layout the item page uses", rec), o)[1]["metadata"]
O3 = opts("Wide", "Narrow", "Tall", rec="Narrow")                 # the recommended one is the second of three
def mism(rec, o=O3): return ask_read.recommend_mismatch(LAYOUT(rec, o))
for what, rec in (("its label, in any case and with trailing punctuation", "NARROW!"), ("its label in a longer sentence", "Narrow, the one that fits a phone"), ("its letter", "B"),
                  ("its letter and label", "B, Narrow"), ("its letter with a note", "B: fits a phone"), ("'option 2'", "option 2"), ("'#2'", "#2"), ("a number", "2"), ("'the second'", "the second one"),
                  ("'2nd'", "2nd"), ("'option B'", "go with option B"), ("no pick: 'none, your call'", "none, your call"), ("no pick: 'either'", "either works")):
    check(f"3b {what} names the recommended option: no mismatch", mism(rec) == "", (rec, mism(rec)))
OLB = opts("Yes, ship", "Hold it", "Drop it", rec="Yes, ship")
check("3b a Recommend whose leading word is one of the label's words ('ship' for 'Yes, ship') or the label's leading word is in it is none", mism("ship", OLB) == "" and mism("yes", OLB) == "" and mism("Ship it now", OLB) == "")
OLB2 = opts("Cut it back", "Keep it", rec="Cut it back")
check("3b …a leading word that is only an article or a preposition is not a match, so 'the slim one' names none", mism("the slim one", OLB2) == "none", mism("the slim one", OLB2))
check("3b with two options, which the page draws with no letters and the recommended one first, any letter or place counts", mism("A", opts("Wide", "Narrow", rec="Narrow")) == "" and mism("the first", opts("Wide", "Narrow", rec="Narrow")) == "")
check("3b a Recommend that plainly names another option by label, letter or place is a mismatch naming it", mism("Wide") == "Wide" and mism("A") == "Wide" and mism("option 3") == "Tall" and mism("the first") == "Wide" and mism("C, Tall") == "Tall", [mism(x) for x in ("Wide", "A", "option 3", "the first", "C, Tall")])
check("3b a Recommend that names no option by any form is a mismatch of none; 'A new column' is no place", mism("the slim one") == "none" and mism("A new column would do") == "none", (mism("the slim one"), mism("A new column would do")))
check("3b a place past the last option is not read as another option", mism("option 6") == "", mism("option 6"))
got, _all = found(build(*[asking(60 + i, ask("which layout the item page uses", r), O3) for i, r in enumerate(("B", "option 2", "the second", "narrow.", "Narrow, fits a phone"))]))
check("3b through the check: none of those forms is a finding", got == {}, got)
got, _all = found(build(asking(9012, ask("which layout the item page uses", "A"), O3), asking(9010, ask("which layout the item page uses", "the slim one"), O3)))
check("3b …and a plain wrong letter and a Recommend naming nothing each are", set(got) == {"board#9012", "board#9010"} and "names another ('Wide')" in got["board#9012"]["detail"] and "names another" not in got["board#9010"]["detail"], got)

# ---- 3b2. a shared leading word does not pass the wrong option, and "not" turns an option away
def mm(rec, labels, recommended): return ask_read.recommend_mismatch(LAYOUT(rec, opts(*labels, rec=recommended)))
SHIP, USEDB, USEAB = ("Ship now", "Ship later", "Drop it"), ("Use cache", "Use db", "Skip it"), ("Use A", "Use B", "Use C")
check("3b2 a shared leading word names the wrong option: 'Ship later' for 'Ship now', 'Use db' for 'Use cache', 'Use B' for 'Use A' are mismatches naming the other",
      (mm("Ship later", SHIP, "Ship now"), mm("Use db", USEDB, "Use cache"), mm("Use B", USEAB, "Use A")) == ("Ship later", "Use db", "Use B"),
      (mm("Ship later", SHIP, "Ship now"), mm("Use db", USEDB, "Use cache"), mm("Use B", USEAB, "Use A")))
check("3b2 …while the whole recommended label still passes, and a leading word that picks the recommended label out alone passes ('ship' for 'Yes, ship', 'Rename' for 'Rename the field')",
      mm("Ship now", SHIP, "Ship now") == "" and mm("ship", ("Yes, ship", "Hold it", "Drop it"), "Yes, ship") == "" and mm("Rename", ("Rename the field", "Keep it", "Drop it"), "Rename the field") == ""
      and mm("Use A", USEAB, "Use A") == "" and mm("Yes, but later", ("Yes", "Later", "Drop it"), "Yes") == "")
WNT = ("Wide", "Narrow", "Tall")
neg = {"Wide, not Narrow": (WNT, "Narrow", "Wide"), "Narrow, not Wide": (WNT, "Wide", "Narrow"), "Not Wide": (WNT, "Wide", "none"), "Avoid Wait; Close": (("Wait", "Close", "Drop"), "Wait", "Close"),
       "Not B": (WNT, "Narrow", "none"), "Not the third": (WNT, "Tall", "none"), "instead of Narrow, take Wide": (WNT, "Narrow", "Wide"), "rather than Wide, Narrow": (WNT, "Wide", "Narrow"),
       "Don't pick Narrow, take Tall": (WNT, "Narrow", "Tall"), "Never Tall": (WNT, "Tall", "none"), "Skip Wide, go Narrow": (WNT, "Wide", "Narrow"), "Except Wide": (WNT, "Wide", "none")}
got = {r: mm(r, labels, rec) for r, (labels, rec, _w) in neg.items()}
check("3b2 an option, letter or place right after not / no / avoid / never / skip / except / don't / instead of / rather than is turned away: the Recommend names the other option if it names one, else none",
      got == {r: want for r, (_l, _r, want) in neg.items()}, {r: (got[r], neg[r][2]) for r in neg if got[r] != neg[r][2]})
check("3b2 …a Recommend that names the recommended option and turns another away still passes, as does 'Narrow over Wide' with no 'not' between and 'B, not A' (a place for the recommended one)",
      mm("Narrow, not Wide", WNT, "Narrow") == "" and mm("Wide, not Narrow", WNT, "Wide") == "" and mm("Narrow over Wide", WNT, "Narrow") == "" and mm("B, not A", WNT, "Narrow") == "" and mm("Use A, not Use B", USEAB, "Use A") == "")
check("3b2 …a 'not' with a comma after it does not reach the next option ('No, Narrow' names Narrow); the label of a 'no' option still names it ('No change, keep it')",
      mm("No, Narrow", WNT, "Narrow") == "" and mm("No change, keep it", ("No change", "Rework", "Drop it"), "No change") == "")
got, _all = found(build(*[asking(100 + i, ask("which layout the item page uses", r), opts(*lb, rec=rc)) for i, (r, (lb, rc, _w)) in enumerate(neg.items())]))
check("3b2 through the check every turned-away Recommend above is a finding", len(got) == len(neg), (len(got), len(neg)))

# ---- 3b3. option labels in any script: a Greek label is read as words, so the same rules hold (label, other option, no match)
GR = ("έγκριση", "άρνηση", "αναμονή")
GRL = ("χρήση νέας διάταξης", "παλιά διάταξη", "αναμονή")
check("3b3 a Recommend equal to a Greek recommended label (alone, in a sentence, with punctuation, spaced differently) is no mismatch",
      all(mm(r, GR, "έγκριση") == "" for r in ("έγκριση", "έγκριση!", "εγώ έγκριση, συνεχίζουμε αύριο"))
      and mm("Σύσταση: έγκριση.", GR, "έγκριση") == "" and mm("χρήση νέας διάταξης", GRL, "χρήση νέας διάταξης") == "" and mm("χρήση,  νέας  διάταξης", GRL, "χρήση νέας διάταξης") == "",
      [mm(r, GR, "έγκριση") for r in ("έγκριση", "έγκριση!", "εγώ έγκριση, συνεχίζουμε αύριο", "Σύσταση: έγκριση.")])
check("3b3 …a Greek Recommend that names another option's label is a mismatch naming it; one that names no option is none",
      mm("άρνηση", GR, "έγκριση") == "άρνηση" and mm("παλιά διάταξη", GRL, "χρήση νέας διάταξης") == "παλιά διάταξη" and mm("άλλος τρόπος", GR, "έγκριση") == "none", (mm("άρνηση", GR, "έγκριση"), mm("παλιά διάταξη", GRL, "χρήση νέας διάταξης"), mm("άλλος τρόπος", GR, "έγκριση")))
check("3b3 …a decomposed (base letter plus a separate accent mark) Greek Recommend matches the same label, and mixed Greek / English labels match whole",
      mm(unicodedata.normalize("NFD", "έγκριση"), GR, "έγκριση") == "" and mm("Ship έγκριση", ("Ship έγκριση", "Hold άρνηση", "Drop it"), "Ship έγκριση") == "", mm(unicodedata.normalize("NFD", "έγκριση"), GR, "έγκριση"))
check("3b3 …an English label still matches as before, and an English Recommend that differs from the label is still a mismatch",
      mm("Narrow", WNT, "Narrow") == "" and mm("NARROW!", WNT, "Narrow") == "" and mm("Wide", WNT, "Narrow") == "Wide" and mm("the slim one", WNT, "Narrow") == "none")
got, _all = found(build(asking(9179, ask("which layout the item page uses", "έγκριση"), opts(*GR, rec="έγκριση")), asking(9180, ask("which layout the item page uses", "χρήση νέας διάταξης, αύριο"), opts(*GRL, rec="χρήση νέας διάταξης"))))
check("3b3 through the check a Greek Recommend equal to its label is no finding", got == {}, got)
got, _all = found(build(asking(9012, ask("which layout the item page uses", "άρνηση"), opts(*GR, rec="έγκριση")), asking(9010, ask("which layout the item page uses", "άλλος τρόπος"), opts(*GR, rec="έγκριση"))))
check("3b3 …and a Greek Recommend naming another option, or none, is found", set(got) == {"board#9012", "board#9010"} and "names another ('άρνηση')" in got["board#9012"]["detail"], got)
check("3b3 the write-time note (server._options_note, which reads recommend_missing) is quiet for a Greek Recommend that names its label and speaks for one that does not",
      server._options_note(LAYOUT("έγκριση", opts(*GR, rec="έγκριση"))) == "" and "“έγκριση”" in server._options_note(LAYOUT("άρνηση", opts(*GR, rec="έγκριση"))), (server._options_note(LAYOUT("έγκριση", opts(*GR, rec="έγκριση"))), server._options_note(LAYOUT("άρνηση", opts(*GR, rec="έγκριση")))))

NFD_GR = LAYOUT(unicodedata.normalize("NFD", "έγκριση"), opts(*GR, rec="έγκριση"))      # the Recommend typed as separate accent marks; the label is the composed letters
check("3b3 the write gate and the audit agree on decomposed Greek: recommend_missing and server._options_note are quiet for it, as recommend_mismatch is",
      ask_read.recommend_missing(NFD_GR) == "" and server._options_note(NFD_GR) == "" and ask_read.recommend_mismatch(NFD_GR) == "",
      (ask_read.recommend_missing(NFD_GR), server._options_note(NFD_GR), ask_read.recommend_mismatch(NFD_GR)))
check("3b3 …and the label stored decomposed against a composed Recommend, and an NFD Recommend naming another label, are read the same way",
      ask_read.recommend_missing(LAYOUT("έγκριση", opts(*(unicodedata.normalize("NFD", k) for k in GR), rec=unicodedata.normalize("NFD", "έγκριση")))) == ""
      and ask_read.recommend_missing(LAYOUT(unicodedata.normalize("NFD", "άρνηση"), opts(*GR, rec="έγκριση"))) == "έγκριση")

# ---- 3c. options the page cannot read are Yes / No to it
bad = build(
    asking(9070, OPEN, [{"label": "Only", "line": "The one.", "recommended": True}]),                                              # one option
    asking(9042, OPEN, [{"label": "Wide", "line": "Wide.", "recommended": False}, {"label": "Narrow", "line": "Narrow.", "recommended": False}]),   # no recommended one
    asking(9081, OPEN, [{"label": "Wide", "line": "Wide.", "recommended": "true"}, {"label": "Narrow", "line": "Narrow.", "recommended": False}]),   # a string, not a boolean
    asking(9080, ask("whether to ship the retry change", "ship"), [{"label": "Only", "line": "The one.", "recommended": True}]),     # a yes/no Decide: fine whatever is stored
)
got, _all = found(bad)
check("3c options the page rejects (one option, no recommended one, a recommended that is not a boolean) are Yes / No to it: the open question is found and the detail says the options are misshaped",
      set(got) == {"board#9070", "board#9042", "board#9081"} and all("stored options are misshaped" in got[k]["detail"] for k in got), got)
check("3c …a yes/no Decide over them is none", "board#9080" not in got)

# ---- 3d. an ask whose Decide and Recommend cannot be told apart
sep = build(asking(90, "which layout the item page uses?"), asking(91, "Decide: which layout - Recommend: narrow - Stakes: none"), asking(92, "which layout the item page uses?", opts("Wide", "Narrow")))
got, _all = found(sep)
check("3d an ask with no Decide / Recommend separators is not read (the shape gate's and ask-missing's): no finding, no open-question wording", got == {}, got)

# ---- 4. the pass: delivery, once, quiet once rewritten
clear_state()
live = build(asking(9083, OPEN), asking(9040, YESNO), asking(9041, ask("which layout the item page uses", "Narrow"), opts("Wide", "Narrow", rec="Narrow")))
r1 = AR.filing_pass(now=now, items=live, anchors={}, env=env())
msg = [(to, t) for to, t, _f in sent if "ask-options" in t]
check("4 the pass finds the one old ask, sends it once, to the project's -main agent marked for the owner (the owner's own item), with the fix line",
      r1["findings"] == 1 and r1["fresh"] == 1 and len(msg) == 1 and msg[0][0] == "alpha-main" and "board#9083" in msg[0][1] and "[for Oliver]" in msg[0][1]
      and "rewrite the ask with options" in msg[0][1] and "board#9040" not in msg[0][1] and "board#9041" not in msg[0][1], (r1, sent))
sent.clear()
r2 = AR.filing_pass(now=now + 600, items=live, anchors={}, env=env())
check("4 a second pass sends nothing while the item is unwritten", r2["fresh"] == 0 and r2["repeats"] == 1 and not sent, (r2, sent))
rec = json.loads((T / "state/audit/filing.json").read_text())
check("4 …and the record keeps the finding with its send stamp", [f["category"] for f in rec["findings"]] == ["ask-options"] and rec["findings"][0].get("sent"), rec["findings"])
written = dict(live); written["a9083"] = {**live["a9083"], "updated": now + 1200, "written_at": now + 1200}      # written, ask unchanged
sent.clear()
r3 = AR.filing_pass(now=now + 1800, items=written, anchors={}, env=env())
check("4 a write that leaves the ask as it was sends the finding again", r3["fresh"] == 1 and any("board#9083" in t for _to, t, _f in sent), (r3, sent))
rewritten = dict(live); rewritten["a9083"] = asking(9083, ask("which layout the item page uses", "Narrow, the one that fits a phone"), opts("Wide", "Narrow", rec="Narrow"), wrote=now + 2400)[1]
sent.clear()
r4 = AR.filing_pass(now=now + 3000, items=rewritten, anchors={}, env=env())
rec = json.loads((T / "state/audit/filing.json").read_text())
check("4 once the ask is rewritten with options the pass is quiet: no finding, no message, nothing on the record", r4["findings"] == 0 and r4["fresh"] == 0 and not sent and rec["findings"] == [], (r4, sent, rec["findings"]))
sent.clear(); rd = AR.filing_pass(now=now + 4000, items=live, anchors={}, env=env(), dry=True)
check("4 a dry run lists the finding and sends nothing", rd["dry"] is True and [f["category"] for f in rd["detail"]] == ["ask-options"] and not sent, (rd, sent))

if fails:
    print(f"\n{len(fails)} of {len(ran)} checks failed"); sys.exit(1)
print(f"ok: ask options audit scenario, {len(ran)} checks")
