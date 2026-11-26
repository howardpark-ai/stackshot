"""Scenario test for the answer frame, GET /items/<key>/answer-frame (docs/answer-frame.md): one item's answer block for another site of the instance to show in a frame. Fixture data,
the HTTP routes through Starlette's test client, no live store, no network. What the page's script does in a browser (the messages, the sizing, two frames) is tests/answer_frame_check.py.

Covers: [ui] answer_frame_origins takes exactly https://<host>[:<port>] and nothing a header would read as more; a bad entry is a config note and never reaches a header; with the list
empty the address is answered as one no route has, and no response of the board changes; only this route's answers say who may frame them (frame-ancestors, no X-Frame-Options), no-store
and nosniff; a caller with no board session gets the signed_out page, with no word of the item, no token, no redirect, the same for an item that exists and one that does not, without a
read of the store; a signed-in member gets the home page's own question and form with their token and the question's reference; the states open, answered, changed and closed, on a first
load and on a refresh against the question first drawn; everything drawn from an item is escaped and no script text holds item data; the answer goes through POST /items/<key>/answer with
every gate as it was, answered as JSON only to a request that asks for exactly that, recorded under the signed-in member; a GET writes nothing.

    tests/run-suite answer_frame        → exit 0 / 1"""
import hashlib, html.parser, json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="frametest-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"
PARENT = "https://chat.example.com"
PARENT2 = "https://two.example.com:8443"
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
    toml += f'\n[[members]]\nname = "Oliver"\nemails = ["{EMAIL}"]\n\n[[members]]\nname = "Pat <b>"\nemails = ["{EMAIL2}"]\n'
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")
    return toml


TOML = write_toml()
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "store/g", "fleet/a", "state", "brain/projects", "secrets", "locale"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-here", "agents": {}, "back_agents": {}, "status": "active", "board": [], "board_open": 0}}}))
DESC = "Background words that the frame never draws."
SUBJECT = "[home] titleword of item"
ASK = "Decide: whether to ship zebraword · Recommend: yes · Stakes: stakesword either way · By: no date"
ASK2 = "Decide: whether to ship the rewritten giraffeword · Recommend: yes · Stakes: stakesword either way · By: no date"
OPTS = [{"label": "Wait", "line": "Wait for the next release", "recommended": False}, {"label": "Ship", "line": "Ship it now as it is", "recommended": True},
        {"label": "Drop", "line": "Drop the feature", "recommended": False}]


def item(L, i, status="open", **meta):
    (T / f"store/{L}/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"{SUBJECT} {L}{i}", "description": DESC, "status": status,
                                                       "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                       "metadata": {"owner": OWNER, "project": "projects/alpha", "next": "nextword step", **meta}}))


def ask_(i, **more): item("a", i, needs=["decision"], ask=ASK, options=OPTS, **more)


ask_(1, draft="draftword to send as it is", draft_label="Reply")
item("a", 2, needs=["decision"], ask=ASK)                                   # no stored options: Yes and No
item("a", 3)                                                                # on an agent
item("a", 4, status="completed", outcome="done", reason="it worked")        # closed, never asked
for i in range(5, 11): ask_(i)
item("a", 9, state="your-step", step="run the one line `true`")             # a step of his: nothing to pick
ask_(10, until="2099-01-01")     # a decision item on hold: not on his move
EVIL = '"><img src=x onerror=alert(1)></script><script>alert(2)</script>'
item("a", 11, needs=["decision"], ask=f"Decide: whether {EVIL} [go](javascript:alert(3)) · Recommend: yes · Stakes: none · By: no date",
     options=[{"label": 'A"><i>x</i>', "line": f"line {EVIL}", "recommended": True}, {"label": "B", "line": "x", "recommended": False}], draft=f"draft {EVIL}")
OLD = {"ts": now - 7200, "kind": "decision", "choice": "Ship", "via": "board", "ask": ASK}
item("a", 12, answers=[{**OLD, "via": "mail"}, {"ts": now - 60, "kind": "comment", "text": "commentword", "via": "board"}, {"ts": now - 50, "kind": "decision", "step": True, "via": "board"}])   # no answer to a question
ask_(13, answers=[OLD], until="2099-01-01")      # an ask stored after the last answer, not on his move
item("a", 14, answers=[OLD], ask_left={"at": now - 100, "why": "t"})                       # an ask the server took off his move after the last answer
item("a", 15, status="completed", outcome="done", reason="r", answers=[{**OLD, "choice": f"B · {EVIL}", "letter": "B", "choice_line": f"cl {EVIL}", "text": f"note {EVIL}\nsecond line", "ask": f"Decide: q {EVIL} · Recommend: yes"}])
ask_(16)                                                                     # answered through the frame by the second member
ask_(17)
item("a", 18, status="completed", outcome="done", reason="r", needs=["decision"], ask=ASK, options=OPTS)      # closed with its question still stored
item("g", 5, needs=["decision"], ask=ASK, options=OPTS)                      # an item addressed by its number
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
from stackshot.web.ui import render as ui_render, answer_frame as ui_frame
from stackshot.core import config as _cfg, readonly as _ro
from stackshot.model import ids as _ids
from starlette.testclient import TestClient
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._owing_note = lambda debtor: ""
telling.tell_woken = lambda *a, **k: None
delivered = []
answer_svc._answer_deliver = lambda *a, **k: delivered.append(a) or []

# ---- 1. the config key
GOOD = {"https://chat.example.com": PARENT, "https://CHAT.Example.com": PARENT, "https://chat.example.com:443": PARENT, "https://two.example.com:8443": PARENT2,
        "https://localhost": "https://localhost", "https://127.0.0.1:9000": "https://127.0.0.1:9000", "https://a-b.xn--bcher-kva.example:65535": "https://a-b.xn--bcher-kva.example:65535"}
check("an https origin is taken, written as a browser writes it", {k: _cfg.frame_origin(k) for k in GOOD} == GOOD, {k: _cfg.frame_origin(k) for k in GOOD})
BAD = ["http://chat.example.com", "chat.example.com", "//chat.example.com", "wss://chat.example.com", "https://", "https://chat.example.com/", "https://chat.example.com/path",
       "https://chat.example.com?q=1", "https://chat.example.com#f", "https://*.example.com", "https://*", "*", "'self'", "data:", "https://a.example.com https://b.example.com",
       "https://a.example.com;script-src *", "https://a.example.com,https://b.example.com", '"https://a.example.com"', "https://a.example.com'", "https://a.example.com\n", "\nhttps://a.example.com",
       "https://a.example.com\r\nSet-Cookie: x=1", " https://a.example.com", "https://a.example.com ", "https://a.example.com\t", "https://user@a.example.com", "https://user:pw@a.example.com",
       "https://a.example.com:", "https://a.example.com:0", "https://a.example.com:01", "https://a.example.com:65536", "https://a.example.com:80a", "https://-a.example.com", "https://a-.example.com",
       "https://a..example.com", "https://a.example.com.", "https://.example.com", "https://[::1]", "https://" + chr(0xE9) + "x.example.com", "https://" + chr(0x212A) + ".example.com", "https://a_b.example.com",
       "https://" + "a" * 64 + ".example.com", "https://" + ".".join(["abcdefgh"] * 29) + ".com", "https://a.example.com%2f", "https://a.example.com\\", "https://a.example.com\x00", "", None, 1, True, ["https://a.example.com"], {"origin": PARENT}]
check("nothing else is taken: another scheme, a path, query, wildcard, list, quote, space, newline, user, bad port or host", [v for v in BAD if _cfg.frame_origin(v)] == [], [v for v in BAD if _cfg.frame_origin(v)])
C = lambda v: {"ui": {"answer_frame_origins": v}}
check("the default is no origin, from an unset key and from the example config", _cfg.answer_frame_origins({}) == [] and _cfg.answer_frame_origins({"ui": {}}) == [] and _cfg.answer_frame_origins() == []
      and re.search(r"(?m)^answer_frame_origins = \[\]", _instance.base_toml()) is not None and _cfg.answer_frame_notes({}) == [])
check("a value that is not a list names no origin and is a note", all(_cfg.answer_frame_origins(C(v)) == [] and len(_cfg.answer_frame_notes(C(v))) == 1 for v in (PARENT, 3, {"a": PARENT}, True)),
      [_cfg.answer_frame_notes(C(v)) for v in (PARENT, 3)])
MIX = [PARENT, "http://plain.example.com", "https://chat.example.com:443", PARENT2, "https://x.example.com/p", 7]
notes = _cfg.answer_frame_notes(C(MIX))
check("a bad entry is left out and named by its place; the good ones stay, once each", _cfg.answer_frame_origins(C(MIX)) == [PARENT, PARENT2] and [re.search(r"entry (\d+)", n).group(1) for n in notes] == ["2", "5", "6"], (_cfg.answer_frame_origins(C(MIX)), notes))
check("the config's notes carry them", all(n in _cfg.notes(C(MIX)) for n in notes), _cfg.notes(C(MIX)))
check("a note holds no line break and no more than a short piece of the entry", all("\n" not in n and len(n) < 300 for n in _cfg.answer_frame_notes(C(["a\n" + "b" * 500]))), _cfg.answer_frame_notes(C(["a\n" + "b" * 500])))


class Main(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.at = {}; self.scripts = []; self._in = False; self.tags = []; self.root = {}
    def handle_starttag(self, tag, attrs):
        a = dict(attrs); self.tags.append((tag, a))
        if tag == "html": self.root = a
        if tag == "main" and a.get("id") == "aframe": self.at = a
        if tag == "script": self._in = True; self.scripts.append("")
    def handle_endtag(self, tag):
        if tag == "script": self._in = False
    def handle_data(self, data):
        if self._in: self.scripts[-1] += data


def parsed(text):
    p = Main(); p.feed(text); return p


def body_of(text):
    """the frame's own content, as markup"""
    return text.split('<div id="afbody">', 1)[1].split('</div><div id="afmsg"', 1)[0]


OURS = (["SAMEORIGIN"], ["frame-ancestors 'self'"])
framing = lambda r: (r.headers.get_list("x-frame-options"), r.headers.get_list("content-security-policy"))
cookie_for = lambda email, ttl=3600: _signin._ui_sign(json.dumps({"email": email, "exp": time.time() + ttl}))
ME, SECOND = cookie_for(EMAIL), cookie_for(EMAIL2)
tok = lambda g, email=EMAIL: _web_answers._answer_token(email, g)
SAME = {"Origin": BOARD}
JSON = {"Origin": BOARD, "Accept": "application/json"}
NAV = {"Sec-Fetch-Mode": "navigate"}


def digest():
    out = {}
    for p in sorted(STORE.rglob("*")):
        if p.is_file() and ".git" not in p.parts: out[str(p.relative_to(STORE))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out, git("log", "--format=%H").stdout, len(G.pending()), len(delivered)


with TestClient(server.mcp.http_app(), base_url=BOARD) as c:
    def get(path, cookie=ME, headers=None):
        c.cookies.clear()
        if cookie: c.cookies.set(_signin._UI_COOKIE, cookie)
        return c.get(path, headers=headers or {}, follow_redirects=False)
    def post(path, data, headers=SAME, cookie=ME):
        c.cookies.clear()
        if cookie: c.cookies.set(_signin._UI_COOKIE, cookie)
        return c.post(path, data=data, headers=headers, follow_redirects=False)
    def frame(key, query="", **kw):
        r = get(f"/items/{key}/answer-frame{query}", **kw); return r, parsed(r.text)

    OTHERS = [("/", ME), ("/items/a1", ME), ("/items/a1", None), ("/projects/alpha", ME), ("/answer-tokens?ids=a1", ME), ("/healthz", None), ("/nothing/here", ME), ("/items/a999", ME), ("/items/a1/answer-framz", ME)]
    def others(): return [(p, get(p, cookie=ck).status_code, framing(get(p, cookie=ck))) for p, ck in OTHERS]

    # ---- 2. no origin configured: the page does not exist
    before = others()
    check("with the key empty every response of the board says only its own origin may frame it", all(f == OURS for _, _, f in before), before)
    real_mode = _signin._auth_mode
    for mode in ("off", "oauth"):
        _signin._auth_mode = lambda: mode
        for who, ck, hd in (("signed in", ME, NAV), ("not signed in, a page load", None, NAV), ("not signed in, a script's request", None, {"Sec-Fetch-Mode": "cors"})):
            for key in ("a1", "a999", "zz!"):
                a, b = get(f"/items/{key}/answer-frame?lang=en", cookie=ck, headers=hd), get(f"/items/{key}/answer-framz?lang=en", cookie=ck, headers=hd)
                strip = lambda r: {k: v.replace("answer-framz", "answer-frame") for k, v in r.headers.items() if k not in ("date", "set-cookie")}
                check(f"empty key, auth {mode}, {who}, {key}: the address is answered as one no route has",
                      (a.status_code, a.content, strip(a)) == (b.status_code, b.content, strip(b)) and framing(a) == OURS and "zebraword" not in a.text,
                      (a.status_code, b.status_code, strip(a), strip(b), a.text[:200]))
        a, b = post("/items/a1/answer-frame", {}), post("/items/a1/answer-framz", {})
        check(f"empty key, auth {mode}: a POST to the address is refused as to any address that only a GET may reach", (a.status_code, a.content, framing(a)) == (b.status_code, b.content, framing(b)) and a.status_code == 405, (a.status_code, b.status_code))
    _signin._auth_mode = real_mode
    _cfg.CFG.setdefault("ui", {})["answer_frame_origins"] = ["http://plain.example.com", "https://x.example.com/p"]
    r = get("/items/a1/answer-frame")
    check("a list with no good entry is an empty list: no page", r.status_code == 404 and framing(r) == OURS, (r.status_code, framing(r)))

    # ---- 3. configured: the headers, and nothing else of the board changes
    _cfg.CFG["ui"]["answer_frame_origins"] = [PARENT, "https://bad.example.com;script-src", PARENT2, "*"]
    after = others()
    check("with origins configured every other response of the board keeps its headers and status", after == before, [x for x, y in zip(after, before) if x != y])
    FRAMED = ([], [f"frame-ancestors 'self' {PARENT} {PARENT2}"])
    OKHEAD = lambda r: framing(r) == FRAMED and r.headers.get("cache-control") == "no-store" and r.headers.get("x-content-type-options") == "nosniff" and r.headers.get("content-type") == "text/html; charset=utf-8"
    snap = digest()
    r, p = frame("a1")
    check("the frame page: 200, only the configured origins and the board may frame it, no X-Frame-Options, no-store, nosniff", r.status_code == 200 and OKHEAD(r), (r.status_code, dict(r.headers)))
    for what, res, status in (("signed out", get("/items/a1/answer-frame", cookie=None), 200), ("an unknown item", get("/items/a999/answer-frame"), 404), ("closed", get("/items/a3/answer-frame"), 200)):
        check(f"the same headers on the frame page when {what}", res.status_code == status and OKHEAD(res), (res.status_code, dict(res.headers)))
    for res in (get("/items/zz!/answer-frame"), get("/items/a1;x/answer-frame", cookie=None), get("/items/0/answer-frame")):
        check("an address that names no item form is a plain 404 nobody else may frame", res.status_code == 404 and framing(res) == OURS and "zebraword" not in res.text, (res.status_code, framing(res)))
    rp = post("/items/a1/answer-frame", {"token": tok("a1"), "choice": "Ship"})
    check("the address takes no POST", rp.status_code == 405 and framing(rp) == OURS and rd("a", 1)["metadata"].get("answers") is None, rp.status_code)

    # ---- 4. what a signed-in member is shown
    B = ui_render.Board(str(STORE))
    q, form = B.home_ask(B.item("a1"), tok("a1"))
    check("open: the question and the form are the home page's own, with this member's token and the question's reference",
          p.at["data-state"] == "open" and form in r.text and q in r.text and f'name="token" value="{tok("a1")}"' in form and f'name="ref" value="{ui_render.question_ref(B.item("a1"))}"' in form
          and p.at["data-ref"] == ui_render.question_ref(B.item("a1")), (p.at, form[:300]))
    q0, form0 = B.home_ask(B.item("a1"))
    check("the home page's form is as before: no token in it", 'name="token" value=""' in form0 and form0 == form.replace(tok("a1"), "") and q0 == q)
    b = body_of(r.text)
    check("open: nothing preselected, Send disabled until a card or a note", b.count('type="radio" name="choice"') == 3 and " checked" not in b and re.search(r'<button type="submit" class="b main" name="act" value="answer" disabled>', b) is not None, b[:600])
    check("open: the item's draft is there, as on the home page", "draftword" in b and 'class="draft hdraft"' in b, b[:600])
    check("open: no title, background or next line of the item, and no link to the item", all(w not in r.text for w in ("titleword", "Background words", "nextword")) and 'href="/items/a1"' not in b, [w for w in ("titleword", "Background words", "nextword") if w in r.text])
    check("the messages' data: the address's key, the configured origins and nothing else as targets", p.at["data-item"] == "a1" and json.loads(p.at["data-origins"]) == [PARENT, PARENT2] and p.at["data-chan"] == "a1", p.at)
    check("links open in a new tab, the page is not indexed and is sized to the device's width", '<base target="_blank">' in r.text and 'content="noindex,nofollow"' in r.text and 'name="viewport" content="width=device-width,initial-scale=1"' in r.text)
    check("no panel, header or other board chrome", all(x not in r.text for x in ('id="panel"', 'id="layout"', 'id="panel-lang"')) )
    r2, p2 = frame("a2")
    check("an ask with no stored options offers Yes and No", p2.at["data-state"] == "open" and re.findall(r'name="choice" value="([^"]*)"', r2.text) == ["Yes", "No"], re.findall(r'name="choice" value="([^"]*)"', r2.text))
    r5, p5 = frame("5")
    check("an item addressed by its number: the key in the page is the address's, the form posts to that address", p5.at.get("data-item") == "5" and 'action="/items/5/answer"' in r5.text and p5.at["data-chan"] == "g5" and f'value="{tok("g5")}"' in r5.text, p5.at)
    r5g, p5g = frame("g5")
    check("…and by its store id: the key follows the address, the channel is the item's", p5g.at.get("data-item") == "g5" and p5g.at["data-chan"] == "g5" and 'action="/items/5/answer"' in r5g.text, p5g.at)
    for dark in ("dark", "light"):
        check(f"theme={dark} is set on the page", frame("a1", f"?theme={dark}")[1].root.get("data-theme") == dark)
    for q_ in ("", "?theme=", "?theme=blue", '?theme=dark"%20onload="x'):
        check(f"no theme or another value follows the device ({q_!r})", "data-theme" not in frame("a1", q_)[1].root)

    # ---- 5. the language
    LOC = T / "locale"
    (LOC / "ko.json").write_text(json.dumps({"frame.title": "XX-title", "home.send": "XX-send", "frame.signed_out": "XX-signed-out", "js.answer.sending": "XX-sending", "sent.decision": "XX-sent"}), encoding="utf-8")
    _cfg.CFG["ui"]["locale_dir"] = str(LOC); i18n._WARNED.clear(); i18n._LOADED.clear()
    check("the test locale loaded", i18n.available() == ["en", "ko"], i18n.available())
    rk, pk = frame("a1", "?lang=ko&theme=dark")
    check("lang picks the page's language: its html tag, its words, its script's words and notices", pk.root == {"lang": "ko", "data-theme": "dark"} and "XX-send" in rk.text and "<title>XX-title</title>" in rk.text and "XX-sending" in rk.text and json.loads(pk.at["data-msgs"])["decision"] == ["ok", "XX-sent"], (pk.root, pk.at.get("data-msgs")[:200]))
    check("…signed out too", "XX-signed-out" in get("/items/a1/answer-frame?lang=ko", cookie=None).text)
    check("an unknown language is the board's", frame("a1", "?lang=xx")[1].root.get("lang") == "en" and frame("a1", '?lang=ko"<x>')[1].root.get("lang") == "en")
    uiprefs.set_lang(EMAIL, "ko")
    check("with none asked, the member's own board language; asked for, the asked one", frame("a1")[1].root.get("lang") == "ko" and frame("a1", "?lang=en")[1].root.get("lang") == "en" and "XX-send" not in frame("a1", "?lang=en")[0].text)
    uiprefs.set_lang(EMAIL, "en")
    _cfg.CFG["ui"].pop("locale_dir"); i18n._WARNED.clear(); i18n._LOADED.clear()
    msgs = json.loads(p.at["data-msgs"])
    check("the notices are the board's own, the home page's wording where it has one", set(msgs) == set(ui_render.Board._SENT_KEYS) and msgs["stale"] == ["warn", i18n.EN["sent.stale_home"]] and msgs["decision"] == ["ok", i18n.EN["sent.decision"]], msgs)

    # ---- 6. no board session
    _bad_reads = []
    real_board, real_gid = ui_render.Board, _ids._item_gid
    from stackshot.web.routes import answer_frame as rt_frame
    class NoRead:
        _SENT_KEYS = real_board._SENT_KEYS; _css = staticmethod(real_board._css)
        def __init__(self, *a): _bad_reads.append(a); raise AssertionError("a signed-out frame read the store")
    real_route_gid = rt_frame._item_gid
    ui_render.Board = NoRead; rt_frame._item_gid = lambda raw: _bad_reads.append(raw) or ""
    try:
        norm = lambda r, key: re.sub(r'data-drawn="[0-9.]+"', 'data-drawn="T"', r.text).replace(f'"/items/{key}"', '"/items/K"').replace(f'data-item="{key}"', 'data-item="K"')
        callers = [("no cookie", None, None), ("a forged cookie", "forged.cookie", None), ("an expired one", cookie_for(EMAIL, -5), None), ("an address not on the board", cookie_for("eve@example.org"), None),
                   ("a bearer token", None, {"Authorization": "Bearer some-session-token"}), ("a page load", None, NAV), ("a script's request", None, {"Sec-Fetch-Mode": "cors"})]
        for mode, ui_open in (("off", False), ("off", True), ("oauth", False), ("oauth", True)):
            _signin._auth_mode = lambda: mode; _cfg.CFG["auth"]["ui_open"] = ui_open
            for who, ck, hd in callers:
                a, gone = get("/items/a1/answer-frame?was=x&since=0", cookie=ck, headers=hd), get("/items/a999/answer-frame?was=x&since=0", cookie=ck, headers=hd)
                pa = parsed(a.text)
                check(f"signed out ({who}, auth {mode}, ui_open {ui_open}): 200 signed_out, no redirect, the same page for an item that does not exist",
                      a.status_code == gone.status_code == 200 and "location" not in a.headers and "set-cookie" not in a.headers and pa.at.get("data-state") == "signed_out" and norm(a, "a1") == norm(gone, "a999") and OKHEAD(a),
                      (a.status_code, gone.status_code, pa.at))
                check(f"signed out ({who}, auth {mode}, ui_open {ui_open}): no word of the item, no token, no form, only the link to it",
                      all(w not in a.text for w in ("zebraword", "titleword", "draftword", "stakesword", "Ship it now", tok("a1"))) and "<form" not in body_of(a.text)
                      and body_of(a.text) == ui_frame.signed_out_body("/items/a1") and 'href="/items/a1" target="_blank" rel="noopener"' in a.text and pa.at.get("data-ref") == "" and pa.at.get("data-chan") == "",
                      body_of(a.text))
        check("a signed-out page reads nothing of the store", _bad_reads == [], _bad_reads)
    finally:
        ui_render.Board = real_board; rt_frame._item_gid = real_route_gid; _signin._auth_mode = real_mode; _cfg.CFG["auth"]["ui_open"] = False

    # ---- 7. the states, first load
    for key, want, why in (("a3", "closed", "on an agent"), ("a4", "closed", "closed without a question"), ("a18", "closed", "closed with its question still stored"), ("a9", "closed", "a step: nothing to pick"), ("a10", "closed", "on hold"),
                           ("a12", "closed", "only a mail tick, a comment and a step's Done"), ("a13", "closed", "an ask newer than the last answer, not on his move"), ("a14", "closed", "an ask the server took off after the last answer")):
        rr, pp = frame(key); bb = body_of(rr.text)
        check(f"{why}: closed, a line and a board link, nothing to press", pp.at["data-state"] == want and bb == f'<p class="afline">{i18n.EN["frame.closed"]}</p><p class="aflink"><a href="/items/{key}" target="_blank" rel="noopener">{i18n.EN["frame.open_board"]}</a></p>', (pp.at["data-state"], bb[:300]))
        check(f"{why}: no token, no question", tok(key) not in rr.text and "zebraword" not in rr.text and pp.at["data-ref"] == "")
    r999, p999 = frame("a999")
    check("an item the store lacks, signed in: closed, 404, a link to the board's home", r999.status_code == 404 and p999.at["data-state"] == "closed" and 'href="/" target="_blank" rel="noopener"' in body_of(r999.text), (r999.status_code, p999.at))

    # ---- 8. escaping
    r11, p11 = frame("a11"); b11 = body_of(r11.text)
    check("what an item says is escaped: question, options and draft", p11.at["data-state"] == "open" and "<img src=x" not in r11.text and "<script>alert" not in r11.text and "<i>x</i>" not in r11.text and 'href="javascript:' not in r11.text and "&lt;img src=x" in b11 and "&lt;i&gt;x" in b11, b11[:900])
    r15, p15 = frame("a15"); b15 = body_of(r15.text)
    check("…and in a recorded answer: question, choice, its line, the note and the member's name", p15.at["data-state"] == "answered" and "<img src=x" not in r15.text and "<script>alert" not in r15.text and b15.count("&lt;img src=x") >= 4 and "second line" in b15, b15[:900])
    for res, words in ((r, ("zebraword", "draftword", "Ship it now", tok("a1"))), (r11, ("alert(1)", "alert(2)", tok("a11"))), (r15, ("alert(1)", "second line"))):
        scripts = "".join(parsed(res.text).scripts)
        check("no script text holds a word of the item or the token", scripts and all(w not in scripts for w in words), [w for w in words if w in scripts])
    check("the scripts of the page are the same whatever the item", parsed(r.text).scripts == parsed(r11.text).scripts == parsed(get("/items/a1/answer-frame", cookie=None).text).scripts)

    # ---- 9. the script's fixed ends (their behaviour is the browser check's)
    sc = ui_frame._SCRIPT
    check("the one message to the parent carries exactly these fields", "var m={source:'stackshot',kind:'answer-frame',v:1,item:item,height:Math.ceil(document.body.getBoundingClientRect().height),state:state,typing:typing}" in sc)
    check("it is posted only to a configured origin by name", sc.count("parent.postMessage") == 1 and "origins.forEach(function(o){window.parent.postMessage(m,o)})" in sc and "'*'" not in sc and '"*"' not in sc)
    check("a message is taken only from the parent window at a configured origin", "e.source!==window.parent||origins.indexOf(e.origin)<0)return" in sc and "d.kind!=='answer-frame'||d.v!==1" in sc and "typeof d.source!=='string'" in sc)
    check("a GET writes nothing: no item, commit, GitHub job or delivery", digest() == snap, "changed")

    # ---- 10. a refresh against the question first drawn
    def first(key):
        rr, pp = frame(key); return pp.at["data-ref"], pp.at["data-drawn"]
    def again(key, ref, since, **kw):
        rr, pp = frame(key, f"?was={ref}&since={since}", **kw); return rr, pp, body_of(rr.text)
    ref, t0 = first("a6")
    rr, pp, bb = again("a6", ref, t0)
    check("a refresh of an unchanged question: open, with the same reference", pp.at["data-state"] == "open" and pp.at["data-ref"] == ref, pp.at)
    ref7, t7 = first("a7"); item("a", 7, needs=["decision"], ask=ASK2, options=OPTS)
    rr, pp, bb = again("a7", ref7, t7)
    check("the question rewritten: changed, one line and a board link, neither question", pp.at["data-state"] == "changed" and bb == f'<p class="afline">{i18n.EN["frame.changed"]}</p><p class="aflink"><a href="/items/a7" target="_blank" rel="noopener">{i18n.EN["frame.open_board"]}</a></p>'
          and "giraffeword" not in rr.text and "zebraword" not in rr.text and tok("a7") not in rr.text, (pp.at, bb))
    rr, pp = frame("a7")
    check("a reload of the frame shows the new question, open", pp.at["data-state"] == "open" and "giraffeword" in rr.text and pp.at["data-ref"] != ref7, pp.at)
    ref8, t8 = first("a8"); item("a", 8)
    rr, pp, bb = again("a8", ref8, t8)
    check("off his move with no answer: closed", pp.at["data-state"] == "closed" and "zebraword" not in rr.text, pp.at)
    item("a", 8, answers=[OLD])
    check("…an answer older than the frame is not its result", again("a8", ref8, t8)[1].at["data-state"] == "closed")
    for bad in ("", "nan", "inf", "-inf", "x", "1e999"):
        item("a", 8, answers=[{**OLD, "ts": time.time() + 60}])
        check(f"…nor when the frame's time is no time ({bad!r})", again("a8", ref8, bad)[1].at["data-state"] == "closed")
    check("…and a newer one is: answered", again("a8", ref8, t8)[1].at["data-state"] == "answered")
    ref6, t6 = first("a6")
    br = post("/items/a6/answer", {"token": tok("a6"), "choice": "C · Drop", "text": "from the board's page", "ref": ref6, "act": "answer"})
    rr, pp, bb = again("a6", ref6, t6)
    check("answered on the board: the frame's refresh shows the recorded answer", br.status_code == 303 and br.headers["location"] == "/items/a6?sent=decision" and pp.at["data-state"] == "answered" and "Drop" in bb and "from the board&#x27;s page" in bb, (br.status_code, br.headers.get("location"), bb[:500]))
    check("answered: the question, who and when, the card and the note; nothing to press, no form, token or board link",
          "zebraword" in bb and "Answered by Oliver, " in bb and '<span class="alab">C \u00b7 Drop</span>' in bb and "Drop the feature" in bb
          and all(x not in bb for x in ("<input", "<button", "<textarea", "<form", "<a ")) and tok("a6") not in rr.text and pp.at["data-ref"] == "", bb[:700])
    check("…the same on a first load", body_of(frame("a6")[0].text) == bb and frame("a6")[1].at["data-state"] == "answered")

    # ---- 11. answering: the board's one answer path, its gates unchanged
    ref5, t5 = first("a5")
    base = {"token": tok("a5"), "choice": "B · Ship", "text": "a note from the frame", "ref": ref5, "act": "answer", "back": ""}
    before5 = rd("a", 5)
    for what, kw in (("not signed in", {"cookie": None}), ("a bearer token and no cookie", {"cookie": None, "headers": {**JSON, "Authorization": "Bearer some-session-token"}}),
                     ("a forged cookie", {"cookie": "forged.cookie"}), ("another origin", {"headers": {**JSON, "Origin": PARENT}}), ("origin null", {"headers": {**JSON, "Origin": "null"}}),
                     ("neither Origin nor Referer", {"headers": {"Accept": "application/json"}}), ("another member's token", {"cookie": SECOND})):
        res = post("/items/a5/answer", base, **{"headers": JSON, **kw})
        check(f"asking for JSON loosens nothing: {what} is refused", res.status_code == 403 and rd("a", 5) == before5, (res.status_code, res.text[:200]))
    res = post("/items/a5/answer", {**base, "token": tok("a6")}, headers=JSON)
    check("…another item's token too", res.status_code == 403 and rd("a", 5) == before5, res.status_code)
    res = post("/items/a5/answer", {**base, "ref": "0" * 16, "text": ""}, headers=JSON)
    check("a pick on a question that is not the one shown records nothing and says stale", res.status_code == 200 and res.json() == {"sent": "stale"} and (rd("a", 5)["metadata"].get("answers") is None) and "decision" in rd("a", 5)["metadata"]["needs"], (res.status_code, res.text))
    res = post("/items/a5/answer", {**base, "choice": "", "text": " "}, headers=JSON)
    check("an empty Send says empty and records nothing", res.json() == {"sent": "empty"} and rd("a", 5) == before5, res.text)
    res = post("/items/a5/answer", base, headers=JSON)
    a = (rd("a", 5)["metadata"].get("answers") or [{}])[-1]
    check("the frame's send: its code as JSON, no-store, nosniff, no redirect", res.status_code == 200 and res.json() == {"sent": "decision"} and res.headers.get("cache-control") == "no-store" and res.headers.get("x-content-type-options") == "nosniff" and "location" not in res.headers and framing(res) == OURS, (res.status_code, res.text, dict(res.headers)))
    check("…recorded as from the item page: the card, the note, via the board", a.get("choice") == "Ship" and a.get("letter") == "B" and a.get("text") == "a note from the frame" and a.get("via") == "board" and a.get("kind") == "decision" and "decision" not in (rd("a", 5)["metadata"].get("needs") or []), a)
    res = post("/items/a5/answer", base, headers=JSON)
    check("a second Send of the same pick records no second decision", res.json()["sent"] != "decision" and sum(1 for x in rd("a", 5)["metadata"]["answers"] if x.get("kind") == "decision") == 1, (res.text, rd("a", 5)["metadata"]["answers"]))
    check("the refresh after it: answered", again("a5", ref5, t5)[1].at["data-state"] == "answered")
    for i, accept in enumerate((None, "*/*", "text/html", "application/json, text/plain", "text/html,application/json")):
        res = post("/items/a17/answer", {"token": tok("a17"), "text": " ", "act": "comment"}, headers={**SAME, **({"Accept": accept} if accept else {})})
        check(f"any other Accept keeps the redirect ({accept!r})", res.status_code == 303 and res.headers["location"].startswith("/items/a17?sent="), (res.status_code, res.headers.get("location")))
    ref16 = frame("a16", cookie=SECOND)[1].at["data-ref"]
    r16 = frame("a16", cookie=SECOND)[0]
    check("a second member's frame carries their own token", f'value="{tok("a16", EMAIL2)}"' in r16.text and tok("a16") not in r16.text)
    res = post("/items/a16/answer", {"token": tok("a16", EMAIL2), "choice": "A · Wait", "ref": ref16, "act": "answer"}, headers=JSON, cookie=SECOND)
    a = (rd("a", 16)["metadata"].get("answers") or [{}])[-1]
    check("the answer is recorded under the member who is signed in", res.json() == {"sent": "decision"} and a.get("by") == "Pat <b>", (res.text, a))
    check("…and shown with that name", "Answered by Pat &lt;b&gt;, " in frame("a16")[0].text)

    # ---- 12. a read-only standby copy
    real_ro = _ro.is_read_only
    _ro.is_read_only = lambda: True
    try:
        res = get("/items/a1/answer-frame")
        check("on a standby copy the frame page keeps its headers under the banner", res.status_code == 200 and framing(res) == FRAMED and res.headers.get("cache-control") == "no-store" and 'id="aframe"' in res.text, (res.status_code, dict(res.headers)))
    finally:
        _ro.is_read_only = real_ro
    _cfg.CFG["ui"]["answer_frame_origins"] = []
    r = get("/items/a1/answer-frame")
    check("the list emptied again (the key is read live): the page is gone", r.status_code == 404 and framing(r) == OURS and "zebraword" not in r.text, (r.status_code, framing(r)))

print(("ok" if not fails else "FAILED") + f": answer frame scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
