"""Scenario test for how-to under the owner's step (step_howto.py): the real create, update, get, answer, complete, render and audit code on fixture data, no live store, no network.

The shape: metadata.step stays the one-line summary (his one checklist line, the wait checks and the notices read only that); how to do it is metadata.step_howto, kept beside the step and drawn under it.

  1  the detector: a click path, or attach or upload with a link; in doubt none (labels, dates, warnings, quotes, past events, negations, facts, the Goal bullet, a fenced block)
  2  step= on an item whose description holds how-to: the bullets go under the step, one checklist line of his, drawn as a bulleted list on the home row and in Your step, get shows them, Done sends them back
  3  later writes never erase it: the same step again, a reworded one, a split long one sent again; step="none" and a close send it back to the description
  4  later writes never double it: the old description again, a corrected link, an edited click path, a numbered step that says the bullets, a step with its own `- ` lines
  5  the checklist: next sent back with a line edited is taken, an `<owner>:` line already there is adopted, the how-to is drawn under its own step beside his others and after a split step's actions
  6  what stays: another's item, a bullet with a command (still refused when added), one past the step limits, the last text of a description; a long how-to bullet is wrapped at create, so it moves whole
  7  the filing pass names exactly what the move takes, and nothing once it moved

    tests/run-suite step_howto        → exit 0 / 1"""
import json, logging, os, pathlib, re, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="howtotest-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), keywords=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml = _instance.set_person(toml)
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
NAMES = ("home-front", "team-back")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "seen": now0} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "team-back", "status": "active",
                                                                               "board": [], "board_open": 0, "agents": {"home-front": "the front", "team-back": "the back"}, "back_agents": {"team-back": "the back"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
logging.disable(logging.INFO)
from stackshot.web import server, home
from stackshot.web.tools import anchors as _wt_anchors, route as _wt_route, create as _wt_create, update as _wt_update, get as _wt_get, complete as _wt_complete
from stackshot.web import publish as _web_publish, page_debts as _web_page_debts
from stackshot.web.ui import render as ui_render
from stackshot.service import telling, answer as answer_svc
from stackshot.model import step_howto as H, steps as S, states, field_gates as FG, model_guards as MG
from stackshot.audit import audit_checks as AC
from stackshot.core import call_log as _CL
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
telling.tell_woken = lambda *a, **k: None

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))

GOAL = "- Goal: the export app is live"
CLICK = "- In the console: Settings → Apps → New app\n  - pick the name export-app"
ATTACH = "- Attach the signed form from [the form](https://files.example.org/form.pdf)"
FACTS = ["- The app sends the nightly export", "- The old address stays: [notes](https://docs.example.org/notes)"]
DESC = "\n".join([GOAL, FACTS[0], CLICK, ATTACH, FACTS[1]])
KEPT = "\n".join([GOAL, *FACTS])
HOWTO = CLICK + "\n" + ATTACH
LEAD = "create the export app and hand over the form"

gid = lambda i: i if isinstance(i, str) else f"a{i}"      # a fixture's number, or the id the create gave
def path(i): return T / f"store/{gid(i)[0]}/{gid(i)[1:]}.json"
def item(i, desc=DESC, **meta):
    path(i).write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": desc, "status": "open", "updated": now0 - 3600, "state_updated": now0 - 3600, "confirmed": now0 - 3600,
                                   "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "team-back: do the thing", **meta}}))
def rd(i): return json.loads(path(i).read_text())
mt = lambda i: rd(i)["metadata"]
how = lambda i: H.text_of(mt(i))
def upd(i, **kw):
    """The update tool (a session's write) → its reply, with the fix lines the middleware appends."""
    tok = _CL.begin()
    try: out = _wt_update.stackshot_update(gid(i), sender="home-front", **kw)
    finally: fx = _CL.end(tok)
    return out + _CL.reply_note(fx)
his = lambda i: [s["text"] for s in S.view(mt(i), keeper=U["home-front"]) if s["status"] == S.OPEN and s["text"].startswith("Oliver:")]
def refused(i, **kw):
    try:
        return upd(i, **kw) and ""
    except Exception as e:  # noqa: BLE001
        return str(e)
def drawn(i):
    """(the home row, the item page's Your step block, the item page's description block)."""
    b = ui_render.Board(f"{tmp}/store")
    r, m = {r["gid"]: (r, m) for r, m in b.home_pairs()[home.YOUR_MOVE]}[gid(i)]
    page = b.item_html(gid(i), answer={"action": f"/items/{gid(i)}/answer", "token": "TOKEN", "sent": ""})
    step = re.search(r'<div class="iask istep">.*?<form class="ianswer"', page, re.S)
    desc = re.search(r'<div class="desc md">.*?</div>', page, re.S)
    return b.home_row(r, m, home.YOUR_MOVE), step.group(0) if step else "", desc.group(0) if desc else ""
def everywhere(i):
    """Every place of the item a line can stand in: the description, the step, the how-to beside it and next."""
    return "\n".join([rd(i)["description"], str(mt(i).get("step") or ""), how(i), str(mt(i).get("next") or "")])
def bulleted(html_):
    """The how-to as drawn: inside a bulleted list of its own, never a numbered line."""
    at = html_.find('<ul class="stephow">')
    return at >= 0 and "New app" in html_[at:] and "New app" not in html_[:at]
def outside_ol(html_):
    """The how-to list stands in no numbered list: it is no step of its own."""
    head = html_[:html_.find('<ul class="stephow">')]
    return head.count("<ol") == head.count("</ol>")
class _Env:
    def role_map(self): return {}
def found(i, cat="step-howto"):
    return [f for f in AC.filing_findings({f"a{i}": {**rd(i), "gid": f"a{i}"}}, {}, time.time(), _Env())[0] if f["category"] == cat]

# ---- 1. the detector
check("1 the click path (with its sub-line) and the attach bullet are how-to, the Goal and the facts are not", H.howto_bullets(DESC) == [CLICK, ATTACH], H.howto_bullets(DESC))
for name, d in (("one arrow", "- the state goes draft → live"), ("attach with no link", "- attach the form"), ("a link with no such word", "- see [the upload-log](https://x.example.org/upload)"),
                ("attached", "- the form is attached: https://x.example.org/f"), ("the Goal bullet", "- Goal: A → B → C"), ("a fenced block", "```\n- A → B → C\n```"),
                ("a bullet over a fence", "- A → B → C\n  ```\n  x\n  ```"), ("no bullet", "A → B → C"), ("lowercase items", "- Settings → apps → new app"),
                ("a Problem bullet with arrows", "- Problem: Settings → Apps → New app fails with an error"), ("a fact about a page", "- The page Settings → Apps → New app shows the old form"),
                ("a parent with one arrow sub-line", "- The export settings\n  - Settings → Apps"), ("a parent over a click path", "- Where it lives\n  - Settings → Apps → New app"),
                ("quoted words", '- The menu entry reads "Settings → Apps → New app"'), ("a code span", "- The docs call it `Settings → Apps → New app`"),
                ("a warning label", "- Careful: Settings → Apps → Delete"), ("a warning word", "- Warning, Settings → Apps → Delete takes the app away"),
                ("what a path does", "- Settings → Apps → Delete removes every export"), ("a logged time", "- 14:02 Settings → Apps → New app gave an error"),
                ("a day", "- Yesterday Settings → Apps → New app hung"), ("a past event", "- Oliver clicked Settings → Apps → New app twice"),
                ("a negation", "- Do not use Settings → Apps → Delete"), ("attachments", "- Attachments are listed at https://x.example.org/a"),
                ("an upload limit", "- Upload limit is 10 MB, see https://x.example.org/l"), ("a name label", "- Oliver: Settings → Apps → New app")):
    check(f"1 in doubt none: {name}", H.howto_bullets(d) == [], H.howto_bullets(d))
for name, d in (("the breadcrumb arrow", "- Menu › File › Export"), ("quoted labels", '- "Settings" → "Apps" → "New app"'), ("upload with a link", "- Upload the report to [the drive](https://drive.example.org/x)"),
                ("words in a link address do not count", "- Settings → Apps → New app: [guide](https://x.example.org/was-broken)")):
    check(f"1 how-to: {name}", H.howto_bullets(d) == [d], H.howto_bullets(d))
check("1 the first line of a how-to bullet is kept whole when long, a fact is not", H.keeps_whole(CLICK.split("\n")[0]) and not H.keeps_whole(FACTS[0]))

# ---- 2. the real shape: created with the how-to in the background, then his step in one line
made = _wt_create.stackshot_create(subject="[home] make the export app live", description=DESC, project="projects/alpha", sender="home-front", mover="home-front", next="home-front: prepare the form")
one = made.split()[1]
check("2 a create leaves no step of his, so its description is as sent", rd(one)["description"] == DESC and "step" not in mt(one), made)
out = upd(one, step=LEAD)
check("2 the step is the one line as sent and the how-to stands beside it, bound to it", mt(one)["step"] == LEAD and how(one) == HOWTO and mt(one)[H.KEY]["step"] == LEAD and mt(one)["state"] == "your-step", mt(one))
check("2 …the description keeps the Goal and the facts, and the reply says what moved, once", rd(one)["description"] == KEPT and out.count("moved from the description to under the step") == 1 and "2 how-to bullets" in out, (rd(one)["description"], out))
check("2 …it does not call the moved lines dropped", "of the old description" not in out, out)
check("2 one open step of his, its one line, and no how-to line in next", his(one) == [f"Oliver: {LEAD}"] and "New app" not in mt(one)["next"] and "signed form" not in mt(one)["next"], (his(one), mt(one)["next"]))
row, block, desc = drawn(one)
for name, html_ in (("home row", row), ("Your step block", block)):
    check(f"2 the {name} shows the step, then every how-to line once, as a bulleted list", LEAD in html_ and all(html_.count(w) == 1 for w in ("New app", "pick the name export-app", "signed form", "https://files.example.org/form.pdf"))
          and bulleted(html_) and html_.index(LEAD) < html_.index("New app") and outside_ol(html_), html_[:1200])
check("2 the description block shows the facts and no how-to", "nightly export" in desc and "New app" not in desc and "signed form" not in desc, desc)
g = _wt_get.stackshot_get(gid(one))
check("2 get shows the how-to under step:, as step= takes it", f"step: {LEAD}\n{HOWTO}\n" in g, g[:1500])
got = answer_svc._answer(one, "", "", "done")
check("2 one Done ticks it: no step of his stays open", his(one) == [] and [s["status"] for s in S.view(mt(one)) if s["text"].startswith("Oliver:")] == ["done"], (got, S.view(mt(one))))
check("2 …and the how-to goes back to the end of the description, the field with it", rd(one)["description"] == KEPT + "\n" + HOWTO and H.KEY not in mt(one), (rd(one)["description"], mt(one).get(H.KEY)))

# ---- 3. later writes never erase it
item(2)
upd(2, step=LEAD)
out = upd(2, step=LEAD)
check("3 the same step again keeps the how-to, and says nothing of it", how(2) == HOWTO and mt(2)["step"] == LEAD and rd(2)["description"] == KEPT and "how-to" not in out, (how(2), out))
check("3 …still drawn under it", all(bulleted(h) and h.count("signed form") == 1 for h in drawn(2)[:2]))
out = upd(2, step="create the export app and send the form over")
check("3 a reworded one-line step keeps the how-to, moved to the new step, and the reply says so", how(2) == HOWTO and mt(2)[H.KEY]["step"] == "create the export app and send the form over"
      and "stay with the new step" in out and his(2) == ["Oliver: create the export app and send the form over"], (mt(2).get(H.KEY), out, his(2)))
check("3 …drawn under the new step", all(bulleted(h) and "send the form over" in h for h in drawn(2)[:2]))
LONG = ("Open the console and create the export app with the name export-app; then sign the form and attach it to this item; "
        "then tell the back desk that the app is live and the form is in.")
item(15)
out = upd(15, step=LONG)
lines15 = list(mt(15).get("step_lines") or [])
check("3 a long step is split into a summary and his lines, and the how-to goes beside the summary", lines15 and how(15) == HOWTO and mt(15)[H.KEY]["step"] == states.clean(mt(15)["step"]) and rd(15)["description"] == KEPT,
      (mt(15).get("step"), lines15, how(15), out))
_, block, _ = drawn(15)
check("3 …drawn after the split step's actions, never before the first", bulleted(block) and block.index("tell the back desk") < block.index('<ul class="stephow">') and block.count("New app") == 1, block[:1500])
out = upd(15, step=LONG)
check("3 …and the same long step sent again keeps it", how(15) == HOWTO and rd(15)["description"] == KEPT and list(mt(15).get("step_lines") or []) == lines15, (how(15), out))
item(25)
upd(25, step=LEAD)
out = upd(25, step="none")
check("3 step=\"none\" sends the how-to back to the end of the description, and the reply says so", rd(25)["description"] == KEPT + "\n" + HOWTO and H.KEY not in mt(25)
      and "went back to the end of the description" in out and "of the old description" not in out, (rd(25)["description"], out))
item(26)
upd(26, step=LEAD)
_wt_complete.stackshot_complete(gid(26), outcome="dropped", reason="no longer wanted", outcome_text="- It was dropped, nobody wants it", sender="home-front")
check("3 a close sends it back to the description too", rd(26)["status"] == "completed" and rd(26)["description"] == KEPT + "\n" + HOWTO and H.KEY not in mt(26), (rd(26)["description"], mt(26).get(H.KEY)))
moved = {**rd(2), "metadata": {**mt(2), "step": "a step a script set"}}
check("3 a step another write changed (a script, a hand-over) sends it back on the save", H.follow(moved) == 3 and moved["description"] == KEPT + "\n" + HOWTO and H.KEY not in moved["metadata"], moved)

# ---- 4. later writes never double it
item(4)
upd(4, step=LEAD)
out = upd(4, step=LEAD, description=DESC)
check("4 the old description sent again takes the same bullets out again: nothing twice", how(4) == HOWTO and rd(4)["description"] == KEPT and "stand under the step already" in out
      and everywhere(4).count("New app") == 1, (how(4), rd(4)["description"], out))
ATTACH2 = "- Attach the signed form from [the form](https://files.example.org/form-v2.pdf)"
out = upd(4, description="\n".join([GOAL, FACTS[0], CLICK, ATTACH2, FACTS[1]]))
check("4 a description write with a corrected link replaces the how-to: the old link is nowhere, the reply quotes it", how(4) == CLICK + "\n" + ATTACH2 and rd(4)["description"] == KEPT
      and "form.pdf" not in everywhere(4) and "was replaced" in out and "Attach the signed form" in out, (how(4), out))
check("4 …drawn with the new link alone", all("form-v2.pdf" in h and "/form.pdf" not in h for h in drawn(4)[:2]))
CLICK2 = "- In the console: Settings → Apps → Add app\n  - pick the name export-app"
out = upd(4, description="\n".join([GOAL, FACTS[0], CLICK2, ATTACH2, FACTS[1]]))
check("4 an edited click path replaces the old one", how(4) == CLICK2 + "\n" + ATTACH2 and "New app" not in everywhere(4) and all("New app" not in h and h.count("Add app") == 1 for h in drawn(4)[:2]), (how(4), out))
out = upd(4, description="\n".join([GOAL, FACTS[0], "- The form is with the back desk"]))
check("4 a description write with no how-to keeps the how-to", how(4) == CLICK2 + "\n" + ATTACH2 and "with the back desk" in rd(4)["description"], (how(4), out))
item(16)
NUM = "1. In the console: Settings → Apps → New app\n   - pick the name export-app\n2. Attach the signed form from [the form](https://files.example.org/form.pdf)"
out = upd(16, step=NUM)
check("4 a numbered step that says the bullets takes them out of the description: each action once", rd(16)["description"] == KEPT and how(16) == "" and mt(16)["step"].count("New app") == 1
      and "taken out" in out, (rd(16)["description"], how(16), out))
check("4 …drawn once", all(h.count("New app") == 1 and h.count("signed form") == 1 for h in drawn(16)[:2]), drawn(16)[1][:1200])
item(17)
out = upd(17, step=LEAD + "\n" + HOWTO)
check("4 step= with its own `- ` lines: the lead is the step, the lines its how-to, and the same bullets leave the description", mt(17)["step"] == LEAD and how(17) == HOWTO and rd(17)["description"] == KEPT
      and his(17) == [f"Oliver: {LEAD}"] and everywhere(17).count("New app") == 1, (mt(17).get("step"), how(17), rd(17)["description"], his(17)))
item(5, KEPT)
out = upd(5, step="open the console and add the app\n* pick Apps, then **New app**\n    the one at the top\n- say done")
check("4 a lead line with its own lines (any marker, a wrapped line joined) is the step and its how-to", mt(5)["step"] == "open the console and add the app"
      and how(5) == "- pick Apps, then **New app** the one at the top\n- say done" and his(5) == ["Oliver: open the console and add the app"], (mt(5).get("step"), how(5), his(5)))
out = upd(5, step="open the console and add the app\n- pick Apps, then **New app**\n- say ready")
check("4 …sent again with other lines, they replace the old, quoted once", how(5) == "- pick Apps, then **New app**\n- say ready" and "say done" in out and "say done" not in everywhere(5)
      and all("say ready" in h and "say done" not in h for h in drawn(5)[:2]), (how(5), out))
item(28)
out = upd(28, step="open the console\n- then say done")
check("4 …and a step's own lines leave description how-to they do not say where it is, said so", how(28) == "- then say done" and rd(28)["description"] == DESC and "stay there" in out, (how(28), out))

# ---- 5. the checklist and the drawing
WAITS = [x for x in ("  - wait for the green tick before you save", "  - wait until the green tick shows", "  - once the green tick shows, save") if MG.wait_lines(f"Oliver: do it\n{x}")[0]]
check("5 the fixture: a sub-line that a line of next would read as a wait", WAITS, WAITS)
CLICKW = "- In the console: Settings → Apps → New app\n" + (WAITS or ["  - wait for the green tick"])[0]
item(18, "\n".join([GOAL, FACTS[0], CLICKW, FACTS[1]]), next="team-back: do the thing\nteam-back: check the logs")
upd(18, step=LEAD)
check("5 the moved sub-line is beside the step, not in next", how(18) == CLICKW and "green tick" not in mt(18)["next"], (how(18), mt(18)["next"]))
err = refused(18, next=mt(18)["next"].replace("check the logs", "check the server logs"))
check("5 next sent back with another line edited is taken, not refused as a wait", err == "" and "check the server logs" in mt(18)["next"] and how(18) == CLICKW, err)
check("5 …and the filing pass reads no wait in it", found(18, "reads-as-wait") == [], found(18, "reads-as-wait"))
item(19, next=f"team-back: do the thing\nOliver: {LEAD}")
upd(19, step=LEAD)
check("5 his line already in next is adopted: one open step of his", his(19) == [f"Oliver: {LEAD}"] and how(19) == HOWTO, (his(19), mt(19)["next"]))
row, block, _ = drawn(19)
check("5 …the how-to drawn once, under the step", all(bulleted(h) and h.count("New app") == 1 and h.index(LEAD) < h.index("New app") for h in (row, block)), block[:1200])
item(20, next="team-back: do the thing\nOliver: read the note first")
upd(20, step=LEAD)
row, block, _ = drawn(20)
def under_own(h):
    """His two steps numbered 1 and 2, the step's own line second, the how-to inside it: never numbered ahead of his other step."""
    ol = re.search(r'<ol class="stepol">.*</ol>', h, re.S)
    if not ol: return False
    o = ol.group(0); at = o.find('<ul class="stephow">')
    return at > 0 and o[:at].count("<li>") == 2 and o.index("read the note first") < o.index(LEAD) < at and o.count("New app") == 1
check("5 beside another step of his, the how-to is drawn under its own step, after the other", len(his(20)) == 2 and all(under_own(h) for h in (row, block)), block[:1500])

# ---- 6. what stays
item(6)
upd(6, description=DESC + "\n- one more fact")
check("6 an item that is not his turn is untouched", rd(6)["description"] == DESC + "\n- one more fact" and "step" not in mt(6) and H.KEY not in mt(6), rd(6))
cmd = "- Shell → Tools → Run `ssh -t box-a 'uptime'`"
check("6 the fixture: the command bullet reads as how-to", H.howto_bullets(cmd) == [cmd], H.howto_bullets(cmd))
item(7, f"{KEPT}\n{cmd}", state="your-step", step=LEAD, mover="Oliver")
err = refused(7, description=f"{KEPT}\n{cmd}\n- one more fact")
check("6 a bullet with a command stays in the description", mt(7)["step"] == LEAD and how(7) == "" and cmd in rd(7)["description"], (err, mt(7)))
item(8, KEPT)
err = refused(8, step=LEAD, description=f"{KEPT}\n{cmd}")
check("6 …and a write that adds one is refused as before", "description: it holds a shell command" in err and rd(8)["description"] == KEPT, err)
long_ = "- Console → Apps → New: " + "very long " * 55
item(9, f"{KEPT}\n{long_}\n{ATTACH}")
upd(9, step=LEAD)
check("6 a bullet past the step's line limit stays, the one that fits moves", how(9) == ATTACH and rd(9)["description"] == f"{KEPT}\n{long_}", (how(9), rd(9)["description"]))
many = [f"- Menu → Page → Field {n}" for n in range(states.STEP_LINES + 2)]
item(10, "\n".join([GOAL, *many]))
upd(10, step=LEAD)
check("6 …and so do the bullets past its line count", how(10).split("\n") == many[:states.STEP_LINES - 1] and rd(10)["description"].split("\n") == [GOAL, *many[states.STEP_LINES - 1:]], rd(10)["description"])
item(11, ATTACH)
upd(11, step=LEAD)
check("6 the last text of a description is never taken", rd(11)["description"] == ATTACH and how(11) == "", rd(11))
_maxl, lmax = FG._description_limits()
longb = "- In the console: Settings → Apps → New app. Fill in each field with the values on the sheet."
while len(longb) <= lmax + 20: longb += " Keep the default for the rest of it."
made = _wt_create.stackshot_create(subject="[home] the long one", description="\n".join([GOAL, FACTS[0], longb, FACTS[1]]), project="projects/alpha", sender="home-front", mover="home-front",
                                   next="home-front: prepare the form")
two = made.split()[1]
dl = rd(two)["description"].split("\n")
check("6 a long how-to bullet is wrapped at create, never split into sibling bullets", sum(ln.startswith("- In the console") for ln in dl) == 1 and sum(ln.startswith("- ") for ln in dl) == 4, dl)
upd(two, step=LEAD)
check("6 …so it moves whole: every word of it under the step, none left behind", how(two).startswith("- In the console") and how(two).rstrip().endswith("rest of it.")
      and rd(two)["description"] == "\n".join([GOAL, *FACTS]) and " ".join(how(two).replace("\n  - ", " ").split()) == " ".join(longb.split()), (how(two), rd(two)["description"]))

# ---- 7. the filing pass
item(12, state="your-step", step=LEAD, mover="Oliver", next="")
f = found(12)
check("7 his turn with how-to only in the description is a finding with a fix, asking nothing of him", len(f) == 1 and "2 how-to bullets" in f[0]["detail"] and f[0]["fix"] == AC.FIX["step-howto"]
      and not AC.needs_person("step-howto") and "step-howto" in AC.CHECKS_FILING, f)
check("7 …it names what the move takes", [b for b in H.pending(rd(12))] == [CLICK, ATTACH], H.pending(rd(12)))
upd(12, step=LEAD)
check("7 …gone once it stands under the step", found(12) == [] and how(12) == HOWTO, found(12))
item(13)
check("7 an item that is not his turn is none", found(13) == [], found(13))
item(22, f"{KEPT}\n{cmd}", state="your-step", step=LEAD, mover="Oliver", next="")
item(23, f"{KEPT}\n{long_}", state="your-step", step=LEAD, mover="Oliver", next="")
item(27, ATTACH, state="your-step", step=LEAD, mover="Oliver", next="")
check("7 a bullet the move never takes is never a finding (a command, past the limits, the last text)", found(22) == [] and found(23) == [] and found(27) == [], (found(22), found(23), found(27)))

print(f"\n{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
