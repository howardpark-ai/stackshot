"""Scenario test for the item brief, GET /items/<key>/brief, and the panel the home page opens it in (docs/board-ui.md). Fixture data, the HTTP routes through Starlette's test client,
no live store, no network. What the page's script does in a browser (opening, closing, Back, drafts, sending, failures, the installed app, the live refresh) is tests/brief_check.py.

Covers: the brief is behind the same sign-in as the item's page and answers an unknown or malformed address with a 404; an old form of an id goes to the one address, the query kept; a GET
writes nothing; its answer boxes are the item page's own (same forms, fields and buttons, for each viewer and item) and post to the one answer route with every gate as it was; the notice
after a send, the codes that keep the box and the codes that mean something was written; what the brief shows (the item's link, the question, the recommendation, the choices or the step, the draft, the box) and
leaves out, nothing twice and no section headings; what bears on it (stakes, date, the first lines of the background) and the sentences that explain a control sit behind a "?" with a role="tooltip" the button names;
no visible word names the view; nothing drawn from an item reaches the page unescaped; the home page carries one empty panel and its
script, its rows' links stay the item pages' own, and the item's page is as it was; the words follow the viewer's language; the scripts parse.

    tests/run-suite brief        → exit 0 / 1"""
import hashlib, html.parser, json, logging, os, pathlib, re, shutil, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="brieftest-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
EMAIL, EMAIL2 = "oliver@example.org", "pat@example.org"


def write_toml():
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    toml = _instance.set_person(toml)
    for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                     (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'),
                     (r'(?m)^allowed_emails = \[[^\]]*\]', f'allowed_emails = ["{EMAIL}", "{EMAIL2}"]'), (r'(?m)^ui_open = true', 'ui_open = false')):
        toml, n = re.subn(pat, rep, toml); assert n == 1, pat
    toml += f'\n[[members]]\nname = "Oliver"\nemails = ["{EMAIL}"]\n\n[[members]]\nname = "Pat"\nemails = ["{EMAIL2}"]\n'
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")


write_toml()
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state", "brain/projects", "secrets", "locale"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-here", "agents": {}, "back_agents": {}, "status": "active", "board": [], "board_open": 0}}}))
BULLETS = [f"- point{w} of the background" for w in ("one", "two", "three", "four", "five", "six", "seven")]
DESC = "\n".join(BULLETS)
SUBJECT = "[home] titleword of item"
ASK = "Decide: whether to ship zebraword · Recommend: yes recoword · Stakes: stakesword either way · By: no date"
OPTS = [{"label": "Wait", "line": "Wait for the next release", "recommended": False}, {"label": "Ship", "line": "Ship it now as it is", "recommended": True},
        {"label": "Drop", "line": "Drop the feature", "recommended": False}]


def item(L, i, status="open", description=DESC, subject=SUBJECT, **meta):
    (T / f"store/{L}/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"{subject} {L}{i}", "description": description, "status": status,
                                                       "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                       "metadata": {"owner": OWNER, "project": "projects/alpha", "next": "nextword step", **meta}}))


def ask_(i, **more): item("a", i, needs=["decision"], ask=ASK, options=OPTS, **more)


PAST = [{"ts": now - 900 + n, "kind": "decision", "choice": f"pick{n}word", "text": f"words{n}", "via": "board", "by": "Pat", "ask": ASK} for n in range(1, 5)]
PAST += [{"ts": now - 100, "kind": "comment", "text": "commentword", "via": "board"}]
ask_(1, draft="draftword to send as it is", draft_label="Reply", answers=PAST)
item("a", 2, needs=["decision"], ask=ASK)                                   # no stored options: Yes and No
item("a", 3, description=f"{SUBJECT} a3")                                   # on an agent; its description only repeats the subject
item("a", 4, status="completed", outcome="done", reason="it worked", outcome_text="outcomeword shipped")
ask_(5, until="2099-01-01")                                                  # on hold
item("a", 6, needs=["decision"], ask="Decide: whether to plainword · Recommend: nothing recoword · Stakes: none · By: 2099-03-04",
     options=[{"label": "Left", "line": "go left", "recommended": False}, {"label": "Right", "line": "go right", "recommended": False}])
item("a", 7, description="\n".join(BULLETS[:6]))
item("a", 9, state="your-step", step="run the one line `true`", needs=["home-here"])      # a step of his: nothing to pick
EVIL = '"><img src=x onerror=alert(1)></script><script>alert(2)</script>'
item("a", 11, subject=f"[home] {EVIL}", description=f"- {EVIL}\n- [go](javascript:alert(3))", needs=["decision"], ask=f"Decide: whether {EVIL} [go](javascript:alert(3)) · Recommend: yes · Stakes: {EVIL} · By: {EVIL}",
     options=[{"label": 'A"><i>x</i>', "line": f"line {EVIL}", "recommended": True}, {"label": "B", "line": "x", "recommended": False}], draft=f"draft {EVIL}",
     answers=[{"ts": now - 60, "kind": "decision", "choice": f"{EVIL}", "text": EVIL, "via": "board", "by": EVIL}])
for n in (12, 13, 14, 15): ask_(n)
item("a", 16, needs=["decision"], ask='"><img src=x onerror=alert(4)> [go](javascript:alert(5))', description="- five\n- of\n- these\n- and\n- no more")      # a short ask in no set form, which the brief draws as the page does
item("a", 18, needs=["decision"], ask="Decide: has relayword arrived? · Options: tailword or drop", options=OPTS)      # no set form, as a wait's own question: its options are stored too
item("a", 19, needs=["decision"], ask="Decide: has relayword arrived? · Options: tailword or drop")                    # …and the same line with none stored
item("g", 5, needs=["decision"], ask=ASK, options=OPTS)                      # an item addressed by its number
ART = "https://claude.ai/artifact/00000000-0000-4000-8000-000000000053"       # a made-up mockup page
item("a", 17, description=f"- [mockup]({ART})", needs=["decision"], ask=ASK, options=OPTS)
(T / "store/next-id").write_text("20"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
logging.disable(logging.INFO)
fails = []; ran = []


def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))


def rd(L, i): return json.loads((T / f"store/{L}/{i}.json").read_text())
STORE = T / "store"

from stackshot.web import server, i18n, uiprefs
from stackshot.web.tools import anchors as _wt_anchors, route as _wt_route
from stackshot.github import ghsync as G
from stackshot.service import answer as answer_svc, telling
from stackshot.web import publish as _web_publish, page_debts as _web_page_debts, answers as _web_answers
from stackshot.web.auth import signin as _signin
from stackshot.web.ui import brief as ui_brief, answer_frame as ui_frame, explain as _explain, render as ui_render
from stackshot.core import config as _cfg, members as _members
from stackshot.model import ids as _ids
from starlette.testclient import TestClient
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
telling.tell_woken = lambda *a, **k: None
delivered = []
answer_svc._answer_deliver = lambda *a, **k: delivered.append(a) or []


class Doc(html.parser.HTMLParser):
    """The tags of a page, its scripts, its answer forms (each as what it would post) and the text a reader sees, tooltips apart."""
    VOID = {"br", "img", "input", "meta", "link", "hr", "source", "wbr"}

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.tags, self.scripts, self.forms, self.stack, self.seen, self.tips = [], [], [], [], [], {}
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs); self.tags.append((tag, a))
        if tag == "form" and "ianswer" in (a.get("class") or "").split():
            self.forms.append({"action": a.get("action"), "method": a.get("method"), "kind": sorted(k for k in a if k.startswith("data-")), "fields": [], "open": True})
        f = self.forms[-1] if self.forms and self.forms[-1]["open"] else None
        if f is not None and tag in ("input", "textarea", "button", "select") and a.get("name"):
            f["fields"].append((tag, a.get("type") or "", a.get("name"), a.get("value") or ""))
        if tag not in self.VOID:
            self.stack.append((tag, a))
        if tag == "script": self.scripts.append("")

    def handle_endtag(self, tag):
        if tag == "form" and self.forms: self.forms[-1]["open"] = False
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]; break

    def handle_data(self, data):
        tags = [t for t, _ in self.stack]
        if "script" in tags:
            self.scripts[-1] += data; return
        if "style" in tags: return
        tip = next((a for _, a in self.stack if a.get("role") == "tooltip"), None)
        if tip is not None: self.tips[tip.get("id")] = self.tips.get(tip.get("id"), "") + data
        elif not any("hidden" in a for _, a in self.stack): self.seen.append(data)

    def shown(self): return " ".join(" ".join(self.seen).split())
    def posts(self): return [(f["action"], f["method"], f["kind"], f["fields"]) for f in self.forms]


def article(text):
    """the brief's own markup, with its opening tag"""
    return '<article class="bitem"' + text.split('<article class="bitem"', 1)[1].split("</article>", 1)[0] + "</article>"


cookie_for = lambda email, ttl=3600: _signin._ui_sign(json.dumps({"email": email, "exp": time.time() + ttl}))
ME, SECOND = cookie_for(EMAIL), cookie_for(EMAIL2)
tok = lambda g, email=EMAIL: _web_answers._answer_token(email, g)
JSON = {"Origin": BOARD, "Accept": "application/json"}
NAV = {"Sec-Fetch-Mode": "navigate"}
FETCH = {"Sec-Fetch-Mode": "cors", "Accept": "text/html"}


def digest():
    out = {}
    for p in sorted(STORE.rglob("*")):
        if p.is_file() and ".git" not in p.parts: out[str(p.relative_to(STORE))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out, git("log", "--format=%H").stdout, len(G.pending()), len(delivered)


# ---- 1. a description cut where it can be
P = ui_brief.pieces
check("one piece per bullet, with what is indented under it", P("- a\n- b\n  - b one\n  more b\n- c") == ["- a", "- b\n  - b one\n  more b", "- c"], P("- a\n- b\n  - b one\n  more b\n- c"))
check("a paragraph is one piece, a blank line ends it", P("x\ny\n\nz\n") == ["x\ny", "z"], P("x\ny\n\nz\n"))
check("numbered lines and headings start pieces of their own", P("## h\ntext\n1. one\n2. two") == ["## h\ntext", "1. one", "2. two"], P("## h\ntext\n1. one\n2. two"))
FENCED = "intro\n```\n- not a cut\n\n- nor this\n```\n- after"
check("a fenced block is never cut", P(FENCED) == ["intro", "```\n- not a cut\n\n- nor this\n```", "- after"], P(FENCED))
check("a line that only quotes words in three backticks opens no fence", P("```one word``` first\n- a\n- b") == ["```one word``` first", "- a", "- b"], P("```one word``` first\n- a\n- b"))
LONG = "````\n```\n- inside\n````\n- after"
check("a fence ends only at as many marks as opened it", P(LONG) == ["````\n```\n- inside\n````", "- after"], P(LONG))
INFO = "```\n```py\n- inside\n```\n- after"
check("a line with words after its marks ends no fence", P(INFO) == ["```\n```py\n- inside\n```", "- after"], P(INFO))
TILDE = "~~~ a`b\n```\n- inside\n~~~~\n- after"
check("a tilde fence ends at tildes, as many or more", P(TILDE) == ["~~~ a`b\n```\n- inside\n~~~~", "- after"], P(TILDE))
check("an indented block under a bullet stays with it across a blank line", P("- a\n\n  still a\n- b") == ["- a\n\n  still a", "- b"], P("- a\n\n  still a\n- b"))
check("list lines join as one list, paragraphs stay apart", ui_brief._join(["- a", "- b", "tail", "other", "## h", "- c"]) == "- a\n- b\n\ntail\n\nother\n\n## h\n\n- c", ui_brief._join(["- a", "- b", "tail", "other", "## h", "- c"]))

with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    def get(path, cookie=ME, headers=None):
        c.cookies.clear()
        if cookie: c.cookies.set(_signin._UI_COOKIE, cookie)
        return c.get(path, headers=headers or {}, follow_redirects=False)
    def post(path, data, headers=JSON, cookie=ME):
        c.cookies.clear()
        if cookie: c.cookies.set(_signin._UI_COOKIE, cookie)
        return c.post(path, data=data, headers=headers, follow_redirects=False)
    def brief(key, query="", **kw):
        r = get(f"/items/{key}/brief{query}", **kw); return r, Doc(article(r.text)) if r.status_code == 200 else None

    real_mode = _signin._auth_mode
    _signin._auth_mode = lambda: "oauth"
    snap = digest()

    # ---- 2. the address, the sign-in
    r, d = brief("a1")
    check("the brief: 200, HTML, not stored", r.status_code == 200 and r.headers.get("cache-control") == "no-store" and r.headers.get("content-type", "").startswith("text/html"), (r.status_code, dict(r.headers)))
    check("it is framed by nobody else, as every page", r.headers.get_list("x-frame-options") == ["SAMEORIGIN"], dict(r.headers))
    out = get("/items/a1/brief", cookie=None, headers=NAV)
    check("signed out, a page load goes to the sign-in and comes back to the brief", out.status_code == 302 and out.headers["location"] == "/ui/login?next=%2Fitems%2Fa1%2Fbrief" and "zebraword" not in out.text, (out.status_code, dict(out.headers)))
    out = get("/items/a1/brief", cookie=None, headers=FETCH)
    check("signed out, a script's request is a plain 401 with no word of the item", out.status_code == 401 and "zebraword" not in out.text and "titleword" not in out.text, (out.status_code, out.text[:200]))
    out = get("/items/a999/brief", cookie=None, headers=FETCH)
    check("signed out, an item that does not exist reads the same", out.status_code in (401, 404), out.status_code)
    for key in ("a999", "999999", "zz!", "a1;x", "0", "board-tmp-nowhere-1", ".."):
        res = get(f"/items/{key}/brief")
        check(f"no brief for {key!r}", res.status_code == 404 and "titleword" not in res.text, (res.status_code, res.text[:200]))
    res = get("/items/g5/brief?sent=decision")
    check("an old form of an id goes to the item's one address, the query kept", res.status_code == 301 and res.headers["location"] == "/items/5/brief?sent=decision", (res.status_code, res.headers.get("location")))
    r5, d5 = brief("5")
    check("the numbered address draws the item and posts to its own answer route", r5.status_code == 200 and d5.forms and d5.forms[0]["action"] == "/items/5/answer" and ("article", "5") in [(t, a.get("data-key")) for t, a in d5.tags], (r5.status_code, d5 and d5.posts()))
    check("a POST to the brief is refused", post("/items/a1/brief", {"token": tok("a1"), "choice": "Ship"}).status_code == 405)

    # ---- 3. the answer boxes are the item page's own
    for who, ck in (("the first member", ME), ("the second member", SECOND)):
        for key in ("a1", "a2", "a3", "a4", "a5", "a6", "a9", "a11", "a16", "5"):
            page_forms = Doc(get(f"/items/{key}", cookie=ck).text).posts()
            _, b = brief(key, cookie=ck)
            check(f"{who}, {key}: the brief posts the forms the item's page posts, field for field", b.posts() == page_forms, (b.posts(), page_forms))
    shapes = {k: [f["kind"] for f in brief(k)[1].forms] for k in ("a1", "a3", "a4", "a9")}
    check("cards on a decision, a comment box on an item on its agent, nothing on a closed one, the step's own box on a step",
          shapes == {"a1": [["data-cards"]], "a3": [["data-comment-only"]], "a4": [], "a9": [["data-step"]]}, shapes)

    # ---- 4. what is shown
    r, d = brief("a1"); art = article(r.text); text = d.shown()
    root = d.tags[0][1]
    check("the article names the item, its fingerprint and the notices that keep the box", root.get("data-key") == "a1" and re.fullmatch(r"[0-9a-f]{6,}", root.get("data-fp") or "") and root.get("data-keep") == " ".join(ui_frame._QUIET), root)
    codes = (root.get("data-recorded") or "").split()
    check("it names the notices that mean something was written, askedback among them, and no other",
          sorted(codes) == sorted(["askedback", "closednote", "comment", "decision", "done", "donenote", "partdone", "stalenote", "stepreply"]) and not set(codes) & set(ui_frame._QUIET), codes)
    heads = [t for t, a in d.tags if a.get("id") == "brief-title"]
    links = lambda doc, href: [a for t, a in doc.tags if t == "a" and a.get("href") == href]
    check("the heading is the item's id and title, as the one link to the item's page", heads == ["h1"] and re.search(r'<h1 class="btitle" id="brief-title"><a href="/items/a1"><span class="ir-id">a1</span> titleword of item a1</a></h1>', art)
          and len(links(d, "/items/a1")) == 1 and "[home]" not in text, (heads, art[:600]))
    q = re.search(r'<div class="iask"><p class="bq"><span>whether to ship zebraword</span><span class="xp" data-xp="brief-more-a1">', art)
    reco = art.find('<p class="breco"><b>Recommend</b> yes recoword</p></div>')
    check("the question is one line with its ? beside it, the recommendation and its reason under it, over the choices",
          q and 0 <= q.start() < reco < art.find('name="choice"') and 'class="badge rec"' in art, art[:2500])
    words = " ".join(text.split())
    check("nothing is shown twice", all(words.count(w) == 1 for w in ("zebraword", "recoword", "titleword", "draftword", "Ship it now as it is")), words)
    gone = [w for w in ("Alpha", "Decide", "Stakes", "stakesword", "no date", "pointone", "Background", "Your answer", "Picked", "Past answers", "pick4word", "words4", "commentword", "Pat", "nextword", "Detail view", "since") if w in words]
    check("the project, stakes, background, past answers and section headings are not drawn", not gone and not [t for t, _ in d.tags if t in ("h2", "h3", "section", "details", "dl")] and art.count("<details") == 0, (gone, words))
    tip = d.tips.get("xp-brief-more-a1", "")
    check("the ? holds the stakes and the first five lines of the background, a line each, and says there is more",
          tip.split("\n") == ["Stakes: stakesword either way", "", "• pointone of the background", "• pointtwo of the background", "• pointthree of the background", "• pointfour of the background", "• pointfive of the background", "…"], tip)
    check("past answers are nowhere in it, the ? included", not [w for w in ("pick2word", "words4", "commentword") if w in art], art[-1500:])
    check("the draft to paste is there", "draftword to send as it is" in text)
    check("a title is cut to one line only where a question or a step follows it", 'class="bhead"' in art and 'class="bhead"' in article(brief("a9")[0].text)
          and 'class="bhead bwhole"' in article(brief("a3")[0].text) and 'class="bhead bwhole"' in article(brief("a4")[0].text))
    r6, d6 = brief("a6")
    a6 = article(r6.text)
    check("with no card recommended the recommendation is still under the question, and the date it is wanted by is in the ?",
          "nothing recoword" in a6.split('<p class="breco">', 1)[1].split("</p>", 1)[0] and "badge rec" not in a6 and "2099-03-04" not in d6.shown() and "By: 2099-03-04" in d6.tips.get("xp-brief-more-a6", ""), (d6.shown(), d6.tips))
    d7 = brief("a7")[1]
    check("one line more is said to be more", d7.tips["xp-brief-more-a7"].endswith("• pointfive of the background\n…") and "pointsix" not in d7.tips["xp-brief-more-a7"], d7.tips)
    d16 = brief("a16")[1]
    check("five lines are all there is, so nothing says more", d16.tips["xp-brief-more-a16"] == "• five\n• of\n• these\n• and\n• no more", d16.tips)
    r17, d17 = brief("a17"); a17 = article(r17.text)
    check("a question's mockup link sits beside it, ahead of the ?",
          re.search(r'<p class="bq"><span>whether to ship zebraword <a class="mockup" href="' + re.escape(ART) + '"', a17) and "recoword" in d17.shown() and d17.shown().count("Mockup") == 1, (d17.shown(), a17[:300]))
    asked = lambda k: re.sub(r"<[^>]+>", "", re.search(r'<p class="bq"><span>(.*?)</span>', brief(k)[0].text).group(1))
    check("a question in no set form loses its label, and its options where they are drawn as choices", asked("a18") == "has relayword arrived?" and "tailword" not in article(brief("a18")[0].text).split('<form', 1)[0]
          and 'name="choice"' in article(brief("a18")[0].text), (asked("a18"), article(brief("a18")[0].text)[:1500]))
    check("with no options stored its line keeps all it says", asked("a19") == "has relayword arrived? · Options: tailword or drop", asked("a19"))
    r3, d3 = brief("a3"); a3 = article(r3.text)
    check("an item that asks nothing shows its state line; one with only its subject to add has no ?", re.search(r'<div class="bbody"><p class="bstate">.+?</p><form', a3) and not d3.tips and 'class="iask"' not in a3, a3)
    r4, d4 = brief("a4"); a4 = article(r4.text)
    check("a closed item shows its state, no outcome and no answer box", 'class="bstate"' in a4 and "outcomeword" not in a4 and not d4.forms and "zebraword" not in a4 and "pointone" in d4.tips.get("xp-brief-more-a4", ""), a4)
    r5w, d5w = brief("a5"); a5 = article(r5w.text)
    check("an item on hold that asks shows its question and choices, and no waiting block", 'class="bq"' in a5 and 'class="iwait"' not in a5 and 'name="choice"' in a5, a5[:3000])
    bare = ui_brief.article(ui_render.Board(str(STORE)), "a1", None)[0]; db = Doc(bare)
    listed = " ".join(db.shown().split())
    check("with no answer box the options are listed once under the question, and nothing else is added",
          not db.forms and bare.count('class="iopts"') == 1 and listed.count("Ship it now as it is") == 1 and "Owner" not in listed and "recoword" in listed and bare.find('class="breco"') < bare.find('class="iopts"'), (listed, bare[:2500]))

    # ---- 5. the answer box in the brief
    foot = art.split('<div class="bfoot">', 1)
    check("under the cards: the note and Send, in one foot inside the form", len(foot) == 2 and '<div class="bfoot"><label class="anote"' in art
          and 'value="answer"' in foot[1].split("</form>", 1)[0] and 'name="choice"' not in foot[1] and "</div></form>" in foot[1], art[art.find("bfoot") - 200:][:1500])
    headed = [k for k in ("a1", "a2", "a3", "a9", "5") if re.search(r'<form class="ianswer"[^>]*><b>', article(brief(k)[0].text)) or "<b>Your step</b>" in brief(k)[0].text]
    check("no answer box or step has a heading", not headed, headed)
    fields = lambda doc: [a for t, a in doc.tags if t == "textarea"]
    check("the note box says it is optional", fields(d)[0].get("placeholder") == "Note (optional)", fields(d))
    check("the comment box and the step's box say what they take", fields(d3)[0].get("placeholder") == "Write a comment; the agent on it is told" and fields(brief("a9")[1])[0].get("placeholder"), fields(d3))
    check("a comment box has no foot of cards", 'class="bfoot"' not in r3.text.split('<article', 1)[1])

    def tooltip_ok(doc, tid, words, about):
        buttons = [a for t, a in doc.tags if t == "button" and a.get("aria-describedby") == tid]
        popup = [a for _, a in doc.tags if a.get("id") == tid]
        return (len(buttons) == 1 and "xp-b" in buttons[0].get("class", "").split() and buttons[0].get("type") == "button" and buttons[0].get("aria-label") == about and "name" not in buttons[0]
                and len(popup) == 1 and popup[0].get("role") == "tooltip" and "hidden" in popup[0]
                and doc.tips.get(tid, "").startswith(words) and words not in doc.shown() and not [a for _, a in doc.tags if words in (a.get("title") or "")])
    check("how to send a pick is behind a ? button, not inline", tooltip_ok(d, "xp-brief-pick-a1", "Pick an option or write a note", "Help: Send"), (d.tips, d.shown()[-600:]))
    check("the rest of the question's matter is behind a ? button of its own", tooltip_ok(d, "xp-brief-more-a1", "Stakes: stakesword", "Help: Details") and set(d.tips) == {"xp-brief-more-a1", "xp-brief-pick-a1"}, d.tips)
    r9, d9 = brief("a9"); a9 = article(r9.text)
    check("what Send note needs is behind a ? button, with no hover title left", tooltip_ok(d9, "xp-brief-note-a9", "Write a note to send it", "Help: Send note") and "data-hint" not in a9 and "data-needs-text" in a9, (d9.tips, a9[-1500:]))
    check("a step is shown with its own ? inside the step's block, ahead of the box", re.search(r'<div class="iask istep"><div class="istepbody">.*?</div><span class="xp" data-xp="brief-more-a9">.*?</span></span></div><form class="ianswer" data-step', a9, re.S)
          and "nextword step" in d9.shown() and set(d9.tips) == {"xp-brief-more-a9", "xp-brief-note-a9"}, a9)
    css = r.text.split("<style>", 1)[1].split("</style>", 1)[0]
    check("the inline hint is not drawn in a brief", ".bitem .ahint{display:none}" in css)
    check("the ? is the board's shared control: its style and its script are on the brief's page, once", css.count(_explain.CSS) == 1 and Doc(r.text).scripts.count(_explain.JS) == 1)

    # ---- 6. nothing of an item's text becomes markup
    r11, d11 = brief("a11"); art11 = article(r11.text)
    bad = [(t, a) for t, a in d11.tags if t in ("img", "script", "i") or any(k.startswith("on") for k in a) or str(a.get("href") or "").lower().startswith("javascript:")]
    check("an item's words are text everywhere in the brief", not bad and "alert(2)" in art11 and "<script>alert" not in r11.text, bad)
    tip11 = d11.tips.get("xp-brief-more-a11", "")
    check("…and in the ?, which holds them as the words they are", "<img src=x" in tip11 and "alert(2)" in tip11 and "javascript:alert(3)" not in [a.get("href") for _, a in d11.tags], tip11)
    r16, d16 = brief("a16"); art16 = article(r16.text)
    bad = [(t, a) for t, a in d16.tags if t in ("img", "script") or any(k.startswith("on") for k in a) or str(a.get("href") or "").lower().startswith("javascript:")]
    check("so is a short ask in no set form", not bad and 'class="iask"' in art16 and "alert(4)" in d16.shown() and "<img" not in art16, (bad, art16[:1500]))

    check("a GET writes nothing", digest() == snap)

    # ---- 7. sending from the brief: the one route, its gates, the notices
    def form_data(key, cookie=ME, **more):
        f = brief(key, cookie=cookie)[1].forms[0]
        data = {n: v for t, ty, n, v in f["fields"] if t == "input" and ty == "hidden"}
        data.update(more); return f["action"], data
    action, data = form_data("a12", choice="Ship", act="answer")
    check("the form carries this member's token and the question it shows", data.get("token") == tok("a12") and data.get("ref"), data)
    before = digest()
    for what, res in (("no session", post(action, data, cookie=None)), ("another origin", post(action, data, headers={**JSON, "Origin": "https://other.example.com"})),
                      ("another member's token", post(action, {**data, "token": tok("a12", EMAIL2)})), ("another item's token", post(action, {**data, "token": tok("a13")}))):
        check(f"refused with {what}, nothing written", res.status_code == 403 and digest() == before, (res.status_code, res.text[:200]))
    res = post(action, {**data, "choice": "", "text": ""})
    check("a blank Send writes nothing and says so in a code that keeps the box", res.json() == {"sent": "empty"} and "empty" in ui_frame._QUIET and digest() == before, res.text)
    _, de = brief("a12", "?sent=empty")
    notes = [a for _, a in de.tags if "bsent" in (a.get("class") or "").split()]
    check("the brief read with that code carries its notice, marked as not sent", notes and notes[0].get("data-ok") == "0" and de.forms and "pick an option" in de.shown().lower(), (notes, de.shown()[:300]))
    fp = lambda doc: doc.tags[0][1].get("data-fp")
    check("a notice does not change the fingerprint", fp(de) == fp(brief("a12")[1]), (fp(de), fp(brief("a12")[1])))
    old = fp(brief("a12")[1])
    res = post(action, data)
    check("the pick is recorded under the signed-in member", res.json() == {"sent": "decision"} and rd("a", 12)["metadata"]["answers"][-1].get("choice") == "Ship" and _members.recorded_by(rd("a", 12)["metadata"]["answers"][-1]) == "Oliver", (res.text, rd("a", 12)["metadata"].get("answers")))
    ra, da = brief("a12", "?sent=decision")
    notes = [a for _, a in da.tags if "bsent" in (a.get("class") or "").split()]
    check("the brief read after it says so, marked as sent, and has changed", notes and notes[0].get("data-ok") == "1" and 'class="isent ok" role="status"' in ra.text and fp(da) != old, (notes, fp(da), old))
    check("no notice without a code, or with one the board does not know", 'class="bsent"' not in brief("a12")[0].text and 'class="bsent"' not in brief("a12", "?sent=made-up")[0].text)
    same = fp(brief("a13")[1])
    check("an item nobody touched keeps its fingerprint", fp(brief("a13")[1]) == same)
    it = rd("a", 13); it["metadata"]["ask"] = ASK.replace("zebraword", "otterword"); (STORE / "a/13.json").write_text(json.dumps(it))
    check("a question written again changes the fingerprint", fp(brief("a13")[1]) != same)
    action, data = form_data("a9", act="done")
    res = post(action, data)
    check("a step is ticked from the brief", res.json() == {"sent": "done"}, res.text)
    plain = post(*form_data("a14", choice="Wait", act="answer"), headers={"Origin": BOARD})
    check("without the script the form is the item page's: it lands on the item's page", plain.status_code == 303 and plain.headers["location"] == "/items/a14?sent=decision", (plain.status_code, plain.headers.get("location")))

    # ---- 8. the home page and the item's page
    home = get("/", headers=NAV).text
    hd = Doc(home)
    panels = [a for t, a in hd.tags if t == "aside" and a.get("id") == "brief"]
    check("the home page carries one panel, empty and hidden, a dialog named by the item's title", len(panels) == 1 and panels[0].get("role") == "dialog" and panels[0].get("aria-labelledby") == "brief-title" and "hidden" in panels[0]
          and '<div id="brief-main"></div></aside>' in home, panels)
    acts = [(t, a.get("data-bact"), a.get("aria-label")) for t, a in hd.tags if a.get("data-bact")]
    check("its bar: previous, next, full screen, close", [x[1] for x in acts] == ["prev", "next", "full", "close"] and all(lbl for t, _, lbl in acts if t == "button"), acts)
    scripts = [s for s in hd.scripts if "window.ssBrief={" in s]
    check("its script is there once", len(scripts) == 1, len(scripts))
    check("the live refresh leaves a page with a draft in the panel alone and tells the panel of a newer board", any("ssBrief.draft()){newer=true;return}" in s and "stackshot:newer" in s and "dispatchEvent(new CustomEvent('stackshot:newer'" in s for s in hd.scripts))
    at = {mark: next((n for n, s in enumerate(hd.scripts) if mark in s), -1) for mark in ("window.ssBrief={", "SK='ss-home-scroll'", "ssBrief.takes(a)")}
    check("the installed app's link rule leaves a title the panel takes, and the panel's script reads the address before the home script clears it",
          0 <= at["ssBrief.takes(a)"] < at["window.ssBrief={"] < at["SK='ss-home-scroll'"] and "takes:function(a)" in scripts[0], at)
    check("the box and send-key scripts take a form put in by the script", sum(s.count("addEventListener('stackshot:inserted'") for s in hd.scripts) == 2, [s.count("stackshot:inserted") for s in hd.scripts])
    links = [a.get("href") for t, a in hd.tags if t == "a" and "ir-link" in (a.get("class") or "").split()]
    check("every row's link is still the item's own page", links and all(re.fullmatch(r"/items/" + _ids._ITEM_KEY, h) for h in links), links)
    ipage = get("/items/a1", headers=NAV).text
    check("the item's page is as it was: no brief, no panel, no ? button, its own script", 'class="bitem"' not in ipage and 'id="brief"' not in ipage and "brief-pick-" not in ipage and "window.ssBrief={" not in ipage
          and "<form class=\"ianswer\" data-cards" in ipage and '<div class="bfoot">' not in ipage, [w for w in ('class="bitem"', 'id="brief"', "brief-pick-") if w in ipage])
    full = get("/items/a1/brief", headers=NAV).text
    fd = Doc(full)
    hrefs = [a.get("href") for t, a in fd.tags if t == "a"]
    check("the full page: the board's header (the way home), then the view alone, with one link to the item's page and no panel", '<div id="brief-page"><article class="bitem"' in full and full.count('<article class="bitem"') == 1
          and "/" in hrefs and hrefs.count("/items/a1") == 1 and 'class="bpbar"' not in full and 'id="brief"' not in full and 'id="brief-main"' not in full, hrefs[:20])
    from stackshot.web.i18n_catalog import CATALOG
    named = [k for k, v in CATALOG.items() if "brief" in v.lower() and ("brief" in k)]
    seen = lambda doc, tags: [doc.shown()] + list(doc.tips.values()) + [a.get(n, "") for _, a in tags for n in ("aria-label", "title", "placeholder", "alt")]
    panel = Doc(home.split('<div id="brief-scrim"', 1)[1].split('<div id="brief-toast"', 1)[0])
    said = [x for x in seen(fd, fd.tags) + seen(panel, panel.tags) + seen(d, d.tags) if "brief" in x.lower()]
    check("the view names itself nowhere a person reads: not in its words, labels or tab title", not named and not said and "<title>a1 · titleword of item a1</title>" in full, (named, said[:5]))
    ran_by = {"card": "window.ssCards=", "box": ui_render._ABOX_JS, "send-key": "form.ianswer textarea,form.hanswer textarea", "brief": "getElementById('brief-page')"}
    gone = [name for name, mark in ran_by.items() if sum(mark in s for s in fd.scripts) != 1]
    check("it runs the card, box, send-key and brief scripts once each, not the item page's sender", not gone and not any("location.replace('/items/" in s for s in fd.scripts), (gone, [s[:60] for s in fd.scripts]))

    # ---- 9. the scripts parse
    if shutil.which("node"):
        for name, group in (("home", hd.scripts), ("full", fd.scripts)):
            for n, s in enumerate(x for x in group if "ssBrief" in x or "xp-b" in x or "stackshot:inserted" in x):
                f = T / f"{name}{n}.js"; f.write_text(s, encoding="utf-8")
                p = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True, timeout=60)
                check(f"{name} script {n} is valid JavaScript", p.returncode == 0, p.stderr[:600])

    # ---- 10. the viewer's language
    (T / "locale/ko.json").write_text(json.dumps({"item.ask.recommend": "XX-reco", "item.ask.stakes": "XX-stakes", "item.details": "XX-details", "brief.close": "XX-close", "explain.about": "XX-about {what}", "js.brief.open": "XX-open"}), encoding="utf-8")
    _cfg.CFG.setdefault("ui", {})["locale_dir"] = str(T / "locale")
    uiprefs.set_lang(EMAIL2, "ko")
    r, d = brief("a1", cookie=SECOND)
    check("the brief is drawn in the viewer's language, the ? included", "XX-reco" in d.shown() and d.tips.get("xp-brief-more-a1", "").startswith("XX-stakes: ") and 'aria-label="XX-about XX-details"' in r.text
          and 'aria-label="XX-about Send"' in r.text and "XX-open" in r.text, (d.shown()[:600], d.tips))
    check("another viewer's stays English", "XX-" not in article(brief("a1")[0].text))
    home2 = get("/", cookie=SECOND, headers=NAV).text
    check("the home panel's bar and the row button's words follow it too", 'aria-label="XX-close"' in home2 and "XX-open" in home2, [x for x in re.findall(r'aria-label="[^"]*"', home2.split('<aside id="brief"', 1)[-1][:900])])
    _signin._auth_mode = real_mode

print(("ok" if not fails else "FAILED") + f": brief scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
