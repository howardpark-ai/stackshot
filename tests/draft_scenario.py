"""Scenario test for an item's draft (draft.py) — fixture
data, no live store, no network, no server socket.

  1  the field: create and update take `draft`, the text as written (many lines, Japanese, indentation), at most 20000 characters; get shows a `draft:` block, the brief only says it is there;
     clear_draft=true and draft="none" remove it; a clear does not go with a new text; a close and his Done drop it; a completed item takes none
  2  the page: the item page draws the draft inside the Your step block (inside the step that uses it, labelled "Message to paste", "Email text to paste" for an email, never "Draft") as one code-style block with a Copy button, escaped, its lines kept; a draft on an item that is not in that block still
     shows; the home row's Your move entry puts it under the step line, labelled "Message to paste" with the same Copy; an Agents row does not
  3  the write guard: an update (step=, which stores your-step; an old your-step item is fixture data) that leaves an item in your-step with the owner as the mover, whose step names a text to post, send or paste (Japanese and English stems), is refused
     unless the item has a draft (stored or in the write) or its step or description links the document; the refusal is one line that names `draft` and the link; a write that sets none of
     step, mover or draft is never held up by it; [model] guards = false skips it
  4  the mirror: the issue body carries the draft in a code block; a change says "draft set", "draft edited" or "draft cleared"
  6  the tool text: create and update name draft (and clear_draft) in their parameters and their descriptions

    tests/run-suite draft        → exit 0 / 1"""
import html, json, os, re, subprocess, sys, pathlib, time, logging
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="draft-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml(), keywords=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
toml, n = re.subn(r'(?m)^transcripts = .*$', f'transcripts = ["{tmp}/no-such-root", "{tmp}/transcripts"]', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about the draft text, its writes replace next wholesale; the checklist has its own suite: checklist
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "transcripts/-home-x"): (T / d).mkdir(parents=True)
NAMES = ("home-front", "team-back", "home-stew")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
now0 = time.time(); H = 3600.0; DAY = 86400.0
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "seen": now0} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": "home-stew", "status": "active",
                                                                                "board": [], "board_open": 0, "agents": {"home-front": "the front", "team-back": "the back"}, "back_agents": {"team-back": "the back"}}}}))
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: home-stew\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, status="open", desc=None, subject=None, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject or f"[home] item {i}", "description": desc or DESC, "status": status, "updated": now0 - 3 * H, "state_updated": now0 - 3 * H,
                                                      "confirmed": now0 - 3 * H, "metadata": {"owner": U["home-front"], "project": "projects/alpha", "next": "team-back: do the thing", **meta}}))
def rd(i): return json.loads((T / (f"store/{i[0]}/{i[1:]}.json" if isinstance(i, str) else f"store/a/{i}.json")).read_text())
mt = lambda i: rd(i)["metadata"]
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
sys.path.insert(0, STACK); logging.disable(logging.INFO)
from stackshot.web import server; from stackshot.web.tools import anchors as _wt_anchors; from stackshot.web.tools import route as _wt_route; from stackshot.model import draft as D; from stackshot.github import ghsync; from stackshot.web import home; from stackshot.model import model
from stackshot.web import publish as _web_publish
from stackshot.web import page_debts as _web_page_debts
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import get as _wt_get
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
from stackshot.web.ui import render as ui_render
_web_publish._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
_web_page_debts._refuse_if_owing = lambda debtor: None
telling.tell_woken = lambda *a, **k: None
upd = lambda i, sender="home-front", **kw: server._update(f"a{i}", sender=sender, **kw)
get = lambda i: _wt_get.stackshot_get(f"a{i}")
GUARDS = server._cfg.CFG.setdefault("model", {})

JA = "こんにちは、オリバーです。\n\n  - 第一: 日程はそのままです。\n  - 第二: <b>リンク</b>は https://example.com/a?b=1&c=2 です。\n\nよろしくお願いします。\nThanks, Alex."
POST = "Post the message in #general (the text is on the item)"

# ================================================================ the helpers
check("1 helper: normalize keeps the text as written (indent, blank lines, Japanese), makes the breaks \\n and drops the blank lines around it", D.normalize("\r\n \n" + JA.replace("\n", "\r\n") + "\r\n\r\n  \n") == JA, repr(D.normalize("\r\n \n" + JA + "\n\n")))
check("1 helper: …and keeps a first line's own indentation", D.normalize("\n    code\nline") == "    code\nline", repr(D.normalize("\n    code\nline")))
check("1 helper: none, clear and - clear; an empty value is not a clear", all(D.is_clear(x) for x in ("none", " Clear ", "-")) and not D.is_clear("") and not D.is_clear("none of them"))
check("1 helper: fenced uses a fence longer than any run of backticks in the text", D.fenced("a ``` b") == "````\na ``` b\n````" and D.fenced("plain") == "```\nplain\n```", D.fenced("a ``` b"))
for w in ("投稿", "送信", "転送", "貼り付け", "返信", "下書き", "メッセージ", "メール", "Eメール", "文書を 上げる", "文書 作成", "文書は 別に", "送る", "送り先", "共有", "チームに共有"):
    check(f"3 stem: Japanese {w!r} names a text", D.names_text(f"チャンネルに {w} する") != "" or D.names_text(w) != "", w)
for w in ("post", "Post the update", "send it", "sends", "sending", "sent", "paste this", "pasted", "reply to Kim", "replied", "draft the note", "drafts", "message Kim", "messages", "email Kim", "e-mail Kim", "emailed", "posting", "share", "Share the note with Kim", "sharing it", "forward the email to Kim", "forwarded", "submit the text to the portal", "submitted"):
    check(f"3 stem: English {w!r} names a text", D.names_text(w) != "", w)
for w in ("文書化する", "電子文書管理", "文書名", "文書類", "run `git send-email x`", "open https://example.com/send/now", "read the post-mortem", "install postgres", "check the error message", "the commit message is wrong",
          "read the log message", "run it and send me the output", "send back the result", "reply here when done", "message me when it is done", "email me the log", "画面共有をオンにする", "画面共有", "送別会に行く", "share your screen", "share the screen", "going forward we", "look forward to it", "moving forward", "submit the form", "submit a PR", "submit the pull request", "restart the server", "approve the PR", "Sign the contract", "sala reauth box-a"):
    check(f"3 stem: {w!r} is no text to post", D.names_text(w) == "", D.names_text(w))
check("3 link: a GitHub issue, PR or commit link cannot hold the text", not D.has_link("see https://github.com/example-owner/stackshot/pull/9") and not D.has_link("https://github.com/o/r/issues/5#issuecomment-1")
      and not D.has_link("[c](https://github.com/o/r/commit/abc123)") and not D.has_link("https://www.github.com/o/r/pulls", "https://github.com/o/r/commits/main"), None)
check("3 link: …a doc, Drive, Notion, Slack, a file in a repo and the issues list's lookalikes still count", all(D.has_link(u) for u in (
      "https://docs.google.com/document/d/1/edit", "https://drive.google.com/file/d/1/view", "https://www.notion.so/x-123", "https://x.slack.com/archives/C1/p1", "https://github.com/o/r/blob/main/draft.md",
      "https://gist.github.com/o/1", "https://github.com/o/r/discussions/3", "https://example.com/issues/5")), None)
check("3 link: …one that counts among ones that do not still counts", D.has_link("https://github.com/o/r/pull/1 and https://docs.google.com/document/d/1"), None)
BU = str(server._cfg.get("instance", "board_url") or "").rstrip("/")
check("3 link: the board's own links (the configured public base URL) cannot hold it", bool(BU) and not D.has_link(BU + "/items/12") and not D.has_link(BU) and D.has_link(BU + ".evil.example/x") and D.has_link("https://other.example/" + BU), BU)
check("3 stem: a link in the text is found; a bare word is not", D.has_link("see https://docs.google.com/d/1") and D.has_link("x", "[doc](http://example.com/x)") and not D.has_link("see the doc", "ftp://x", None))

# ================================================================ 1. the field
out = _wt_create._create(subject="[home] filed with a draft", description=DESC, project="projects/alpha", owner="home-front", next="team-back: build it", needs=["team-back"], draft=JA)
gid = (re.match(r"created (\w\d+)", out) or [0, ""])[1]
(T / f"store/{gid[0]}").mkdir(exist_ok=True) if gid else None
check("1 field: create stores the draft as written, many lines, Japanese and indentation", bool(gid) and rd(gid)["metadata"].get("draft") == JA, (out[:200], gid))
g = _wt_get.stackshot_get(gid)
check("1 field: get shows it as a `draft:` block, every line as written", "\ndraft:\n" + JA + "\n" in "\n" + g + "\n", g)
item(1, needs=["team-back"], next="team-back: build it", draft=JA)
bf = server._fmt(json.loads(raw(1)) | {"gid": "a1"}, brief=True)
check("1 field: the brief only says the draft is there (it loads into every session)", "draft: 7 lines" in bf and "オリバー" not in bf, bf)
item(2, needs=["team-back"], next="team-back: build it")
out = upd(2, draft=JA + "\r\n\r\n")
check("1 field: update sets it; the line breaks are made \\n and the blank lines after it dropped", mt(2).get("draft") == JA and "draft:\n" + JA in out, mt(2).get("draft"))
check("1 field: a draft write is a filing edit: no clock moves", rd(2)["state_updated"] == now0 - 3 * H and rd(2)["confirmed"] == now0 - 3 * H, rd(2))
out = upd(2, draft="a second text\nof two lines")
check("1 field: update replaces it", mt(2)["draft"] == "a second text\nof two lines", mt(2))
upd(2, priority="p1")
check("1 field: a write that leaves draft out keeps it", mt(2)["draft"] == "a second text\nof two lines", mt(2))
upd(2, clear_draft=True)
check("1 field: clear_draft=true removes it", "draft" not in mt(2) and "draft:" not in get(2), mt(2))
upd(2, draft="again")
upd(2, draft="none")
check("1 field: draft=\"none\" removes it too", "draft" not in mt(2), mt(2))
upd(2, draft="again"); upd(2, draft="-")
check("1 field: …and \"-\", like the ask", "draft" not in mt(2), mt(2))
refused_nw("1 field: a clear does not go with a new text", 2, lambda: upd(2, draft="new", clear_draft=True), "clear_draft", "does not go with")
upd(2, draft="x" * D.MAX)
check("1 field: a draft of exactly the cap is stored", len(mt(2)["draft"]) == D.MAX, len(mt(2).get("draft", "")))
refused_nw("1 field: a draft over the cap is refused, naming the cap", 2, lambda: upd(2, draft="x" * (D.MAX + 1)), "draft is at most 20000 characters", "20001")
refused("1 field: a create over the cap is refused", lambda: _wt_create._create(subject="[home] too long", description=DESC, project="projects/alpha", owner="home-front", next="team-back: x", needs=["team-back"], draft="y" * (D.MAX + 1)), "draft is at most")
refused_nw("1 field: a draft that is not a string is refused", 2, lambda: upd(2, draft=["a", "b"]), "draft is a string")
item(3, needs=["team-back"], next="team-back: build it", draft="to post")
upd(3, status="completed", outcome="done", reason="finished", description="- It shipped\n- Closed as done\n- Nothing left")
check("1 field: a close drops the draft", "draft" not in mt(3) and rd(3)["status"] == "completed", mt(3))
refused("1 field: a completed item takes no draft", lambda: upd(3, draft="late"), "completed item keeps no draft")
refused("1 field: …nor one passed with the close", lambda: upd(2, status="completed", outcome="done", reason="finished", description="- It shipped\n- Closed as done\n- Nothing left", draft="late"), "completed item keeps no draft")
# his Done
item(4, needs=["team-back"], mover="Oliver", then="team-back", state="your-step", step="paste the text from the item page into #general", draft="the text to paste")
r = server._answer("a4", "", "", "done")
check("1 field: his Done drops the draft with the step", r == "done" and "draft" not in mt(4) and "state" not in mt(4), (r, mt(4)))

# ================================================================ 3. the write guard
item(10, needs=["team-back"], next="team-back: build it")
refused_nw("3 guard: your-step whose step posts a text, no draft, no link: refused in one line that names draft and the link", 10, lambda: upd(10, step=POST), "a10: the step asks", "draft=", "an https:// link", "\"Post\"")
try:
    upd(10, step=POST)
except Exception as e:
    check("3 guard: …a single line", "\n" not in str(e).strip() and str(e).startswith("Refused: "), str(e))
for stem, step in (("投稿", "チャンネルに投稿する"), ("送信", "チームに送信する"), ("転送", "内容を転送"), ("貼り付け", "本文を貼り付け"), ("返信", "田中さんに返信"), ("下書き", "下書きを確認して出す"),
                   ("文書", "お知らせ 文書を 上げる"), ("メッセージ", "スラックのメッセージ"), ("メール", "メール一通"), ("送る", "ファイルを送る"), ("send", "Send the note to Kim"), ("paste", "Paste it into the doc"), ("reply", "Reply on the thread"),
                   ("draft", "Review the draft and ship it"), ("message", "Message Kim"), ("email", "Email Kim today")):
    refused_nw(f"3 guard: {stem!r} in the step is refused without a draft", 10, lambda step=step: upd(10, step=step), "draft=")
out = upd(10, step=POST, draft=JA)
check("3 guard: …with the draft in the same write it stands", mt(10).get("state") == "your-step" and mt(10)["draft"] == JA and "state: your-step" in out, mt(10))
item(11, needs=["team-back"], next="team-back: build it", draft=JA)
upd(11, step=POST)
check("3 guard: …and with a draft already stored", mt(11).get("state") == "your-step", mt(11))
item(12, needs=["team-back"], next="team-back: build it")
upd(12, step=POST + " — text: https://docs.google.com/document/d/1abc/edit")
check("3 guard: a link in the step is the alternative", mt(12).get("state") == "your-step" and "draft" not in mt(12), mt(12))
item(19, needs=["team-back"], next="team-back: build it")
refused_nw("3 guard: a PR link in the step is no document that holds the text", 19, lambda: upd(19, step=POST + " (see https://github.com/example-owner/stackshot/pull/9)"), "draft=", "GitHub issue or PR link does not count")
refused_nw("3 guard: …nor a link to a board item", 19, lambda: upd(19, step=POST + " " + BU + "/items/12"), "draft=")
upd(19, step="Share the figures: https://docs.google.com/document/d/1abc/edit")
check("3 guard: …a doc link does, and share is a stem", mt(19).get("state") == "your-step", mt(19))
item(13, desc="- The text is in https://docs.google.com/document/d/1abc/edit\n- Done when posted", needs=["team-back"], next="team-back: build it")
upd(13, step=POST)
check("3 guard: …and a link in the description", mt(13).get("state") == "your-step", mt(13))
item(14, needs=["team-back"], next="team-back: build it")
upd(14, step="In PowerShell run the command in your Next line and say done", next="team-back: build it\nOliver: run `ssh -t box-a 'sala op reauth box-a --words send'` in PowerShell")
check("3 guard: a step that points at a command in Next, or names no text, needs no draft (code spans are not prose)", mt(14).get("state") == "your-step", mt(14))
item(15, needs=["team-back"], next="team-back: build it")
upd(15, step="Sign the contract and say done")
check("3 guard: …plain words that name no text", mt(15).get("state") == "your-step", mt(15))
# a write that sets none of step, state, mover, draft is never held up
item(16, needs=["team-back"], state="your-step", step=POST, mover="Oliver", then="team-back", next="Oliver: post it")
upd(16, priority="p1")
check("3 guard: an unrelated write to an old your-step item with no draft is not held up", mt(16).get("priority") == "p1", mt(16))
upd(16, next="Oliver: post it, then tell team-back")
check("3 guard: …nor a write of next", "tell team-back" in mt(16)["next"], mt(16))
upd(16, description="- A thing\n- It lives here\n- Done when posted")
check("3 guard: …nor a write of the description", "posted" in rd(16)["description"], rd(16)["description"])
refused_nw("3 guard: a write that sets the step on it is judged", 16, lambda: upd(16, step="Send the update to Kim"), "draft=")
refused_nw("3 guard: …and so is one that sets the mover to the owner", 16, lambda: upd(16, mover="Oliver"), "draft=")
upd(16, draft=JA)
check("3 guard: a draft written on it satisfies the guard", mt(16)["draft"] == JA, mt(16))
refused_nw("3 guard: clearing the draft off a step that posts a text is refused", 16, lambda: upd(16, clear_draft=True), "draft=")
upd(16, clear_draft=True, step=POST + " https://example.com/doc")
check("3 guard: …unless the step links the document in the same write", "draft" not in mt(16), mt(16))
# an agent's stored mover is not his step
check("3 guard: problem(): a stored mover that is an agent is not his step", D.problem({"status": "open", "metadata": {"state": "your-step", "step": POST, "mover": "team-back"}}) == "")
check("3 guard: problem(): a stored mover that is the owner is", "draft=" in D.problem({"status": "open", "metadata": {"state": "your-step", "step": POST, "mover": "Oliver"}}))
check("3 guard: problem(): any other state, and a closed item, are not judged", D.problem({"status": "open", "metadata": {"state": "doing", "step": POST}}) == "" and D.problem({"status": "completed", "metadata": {"state": "your-step", "step": POST}}) == "")
# guards off
item(17, needs=["team-back"], next="team-back: build it")
GUARDS["guards"] = False
upd(17, step=POST)
check("3 guard: [model] guards = false skips it, as the other write guards", mt(17).get("state") == "your-step" and "draft" not in mt(17), mt(17))
GUARDS["guards"] = True
# (the client API's state route is retired: retired_inputs scenario covers its refusal)

# ================================================================ 2. the page
bd = ui_render.Board(f"{tmp}/store")
BOX = {"action": "/items/a4/answer", "token": "TOKEN", "sent": ""}
page = lambda i, **kw: ui_render.Board(f"{tmp}/store").item_html(f"a{i}", **kw)
item(20, subject="[home] post it", mover="Oliver", then="team-back", needs=["team-back"], state="your-step", step=POST, draft=JA, next="team-back: check it")
p20 = page(20, answer=BOX)
blk = re.search(r'<div class="iask istep"><b>Your step</b><div class="istepbody">(.*?)</div></div><form class="ianswer"', p20, re.S)
check("2 page: the Your step block holds the draft under a \"Message to paste\" label with the Copy button just beside it", bool(blk) and '<div class="draft"><div class="dhead"><b class="dlab">Message to paste</b><button type="button" class="b copy" aria-label="Copy the message to paste">Copy</button></div><pre><code>' in blk.group(1) and ">Draft<" not in blk.group(1), (blk.group(1) if blk else p20[:600]))
check("2 page: ...and it is no command block (not .cmd, so not monospace)", bool(blk) and 'class="cmd' not in blk.group(1) and "draft below" not in p20.lower(), None)
code = re.search(r'<div class="draft"><div class="dhead">.*?<pre><code>(.*?)</code></pre>', p20, re.S).group(1)
check("2 page: the text is escaped and keeps every line, space and Japanese character", html.unescape(code) == JA and "<b>リンク</b>" not in code and "&lt;b&gt;リンク&lt;/b&gt;" in code and "\n\n  - 第一" in code, code)
check("2 page: ...and sits right under the step's own text, before the note box and the buttons", p20.index("Post the message") < p20.index('<b class="dlab">Message to paste</b>') < p20.index('<form class="ianswer"') < p20.index('name="act" value="done"') < p20.index('name="act" value="note"'), None)
CSS = ui_render.Board(f"{tmp}/store")._css()
DPRE = CSS.split(".draft pre{")[1].split("}")[0]
check("2 page: the Copy script and the block's style are on the page", "closest('button.copy')" in p20 and "navigator.clipboard" in p20 and "select" in p20 and ".cmd button.copy{" in CSS and "white-space:pre-wrap" in CSS, None)
check("2 page: the draft's text takes the page's own font and keeps its breaks; a command block stays monospace", "font:inherit" in DPRE and "white-space:pre-wrap" in DPRE and "overflow-wrap:anywhere" in DPRE and "font:inherit" in CSS.split(".draft pre code{")[1].split("}")[0] and "font" not in CSS.split(".cmd pre code{")[1].split("}")[0], DPRE)
check("2 page: the copy script reads a draft's text from its own block, beside the label", "closest('.draft')" in p20, None)
item(25, mover="Oliver", then="team-back", needs=["team-back"], state="your-step", step="Post the message in the channel, then run `uv run x y`", draft=JA, next="team-back: check it")
p25 = page(25, answer=BOX)
check("2 page: with a command in the step too, the draft sits between the step's text and the command block", p25.index("Post the message") < p25.index('<b class="dlab">Message to paste</b>') < p25.index('<div class="cmd"><pre><code>uv run x y'), p25[p25.find("Your step"):][:900])
p20b = page(20)
check("2 page: signed out, the step block still carries the draft", 'class="draft"' in p20b and "Your step" in p20b, None)
HOST = "<script>alert(1)</script> & \"q\" <img src=x onerror=alert(1)>"
item(21, mover="Oliver", then="team-back", needs=["team-back"], state="your-step", step=POST, draft=HOST, next="team-back: check it")
p21 = page(21, answer=BOX)
check("2 page: a hostile draft is only text", "<script>alert(1)</script>" not in p21 and "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;q&quot; &lt;img" in p21 and "<img src=x" not in p21, p21[p21.find('class="draft"') - 50:p21.find('class="draft"') + 400])
item(22, mover="Oliver", then="team-back", needs=["team-back"], state="your-step", step="run `uv run x y` and say done", next="team-back: check it")
p22 = page(22, answer=BOX)
check("2 page: an item with no draft draws none", "Your step" in p22 and 'class="draft"' not in p22 and '>Draft<' not in p22, None)
item(23, mover="team-back", needs=["team-back"], draft=JA, next="team-back: write it")
p23 = page(23, answer=BOX)
check("2 page: a draft on an item that is not in the Your step block is still drawn, in a block of its own", 'class="iask idraft"' in p23 and 'class="draft"' in p23 and "Your step" not in p23, p23[:300])
item(24, status="completed", mover=None, draft="stale", outcome="done", reason="x")
check("2 page: a closed item draws none", 'class="draft"' not in page(24, answer=BOX), None)

# the home row
b = ui_render.Board(f"{tmp}/store")
pairs = b.home_pairs()
ym = {r["gid"]: (r, m) for r, m in pairs[home.YOUR_MOVE]}
aw = {r["gid"]: (r, m) for r, m in pairs[home.AGENTS]}
r20 = b.home_row(*ym["a20"], home.YOUR_MOVE)
item(26, mover="Oliver", then="team-back", needs=["team-back"], state="your-step", step="Post the message in the channel, then run `uv run x y`", draft=JA, next="team-back: check it")
b = ui_render.Board(f"{tmp}/store")
pairs = b.home_pairs()
ym = {r["gid"]: (r, m) for r, m in pairs[home.YOUR_MOVE]}
aw = {r["gid"]: (r, m) for r, m in pairs[home.AGENTS]}
r20 = b.home_row(*ym["a20"], home.YOUR_MOVE)
dr = re.search(r'<div class="draft hdraft"><details><summary><span class="dlab">Message to paste</span><button type="button" class="b copy" aria-label="Copy the message to paste">Copy</button></summary><pre><code>(.*?)</code></pre></details></div>', r20, re.S)
check("2 home: a Your move row labels the draft \"Message to paste\" (never \"draft\"), Copy beside the label inside the summary, the text behind it", bool(dr) and html.unescape(dr.group(1)) == JA and "draft below" not in r20, r20[-900:])
check("2 home: ...under the step line, before the note box and its two buttons", r20.index("Post the message") < r20.index('class="draft hdraft"') < r20.index('<form class="hanswer hstep"') < r20.index('name="act" value="done"') < r20.index('name="act" value="note"'), r20[:900])
check("2 home: ...and still inside the row's detail block", r20.index('class="ir-det"') < r20.index('class="draft hdraft"'), None)
check("2 home: ...the step and its Done / Send note form are still the row's", "Send note" in r20 and "Done" in r20 and "Post the message" in r20, r20[:300])
r26 = b.home_row(*ym["a26"], home.YOUR_MOVE)
check("2 home: with a command in the step too, the draft sits between the step's text and the command block", r26.index("Post the message") < r26.index('class="draft hdraft"') < r26.index('<div class="cmd"><pre><code>uv run x y') < r26.index('<form class="hanswer hstep"'), r26[:1200])
r21 = b.home_row(*ym["a21"], home.YOUR_MOVE)
check("2 home: a hostile draft is only text on the row too", "<script>alert(1)</script>" not in r21 and "<img src=x" not in r21 and "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;q&quot; &lt;img" in r21 and 'class="draft hdraft"' in r21, r21[r21.find('class="draft hdraft"') - 50:][:500])
check("2 home: a Your move row without a draft has no marker", "hdraft" not in b.home_row(*ym["a22"], home.YOUR_MOVE), None)
check("2 home: an Agents row never carries it", "a23" in aw and "hdraft" not in b.home_row(*aw["a23"], home.AGENTS), None)
check("2 home: the marker's style is in the page", ".hdraft{" in b._css() and ".hdraft summary{" in b._css(), None)

# ================================================================ 4. the mirror (the issue carries the subject, open or closed and the description alone)
it = json.loads(raw(20)); it["gid"] = "a20"
body = ghsync.body_of("a20", it)
check("4 mirror: the issue body does not carry the draft", "Draft" not in body and JA not in body, body[-600:])
it2 = json.loads(raw(20)); it2["metadata"]["draft"] = "has ``` inside"
none_ = json.loads(raw(20)); none_["metadata"].pop("draft")
check("4 mirror: a draft set, edited or cleared is no change of what the issue carries: no GitHub write", ghsync.mirrored(none_) == ghsync.mirrored(it) == ghsync.mirrored(it2), None)

# ================================================================ 6. the tool text
import inspect
snap = json.loads(pathlib.Path(STACK, "tests/tool_text.snapshot.json").read_text(encoding="utf-8"))["tools"]
check("6 text: create and update take draft, update clear_draft (the snapshot)", "draft" in snap["create"]["parameters"] and "draft" in snap["update"]["parameters"] and "clear_draft" in snap["update"]["parameters"], None)
check("6 text: …as the functions do", {"draft"} <= set(inspect.signature(_wt_create.stackshot_create).parameters) and {"draft", "clear_draft"} <= set(inspect.signature(_wt_update.stackshot_update).parameters), None)
for tool in ("create", "update"):
    d = snap[tool]["description"]
    check(f"6 text: {tool}'s description says what a draft is, the Copy button and that a post or send step needs one", "draft: the text exactly as it is to be posted, sent or pasted" in d and "Copy button" in d
          and "refused unless the item has a draft" in d and "an https:// link" in d and "post, send, paste" in d and "[keywords.draft]" in d and "email" in d
          and "sets the step or mover of an item so that it is his step" in d and "share, forward" in d and "a heuristic, not a complete list" in d and "GitHub issue, pull request or commit link" in d, d[-900:])
check("6 text: get's lines carry the draft: label", "draft:" in snap["get"]["labels"], snap["get"]["labels"])

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": draft scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
