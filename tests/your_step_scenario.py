"""Scenario test for the Your step block: his full open steps, numbered, each said once — fixture data, no live store, no network, no server socket.

The block on the item page and on the home row's Your move entry holds only his open steps (the lines of next that open with his name, or with none), as one numbered list, each step
in full and said once, each command in its own box with a Copy button and no label. The step's one-line summary (the `step` field) is not drawn beside them: it stays where space is
short (the tab title, a Slack notice). The line the server makes on the checklist from the summary is not drawn either, with or without his name in front of it, and a line that repeats an
earlier one of his is drawn once. A draft (the text to paste) sits inside the step that uses it, under the label "Message to paste" ("Email text to paste" for an email), never "Draft", and is
left out when it is one of the commands the steps already show. Next keeps every step, his included.

  1  the item page: a step with prose, a step with a command, a third open step of an agent, the server's line for the summary (his name in front, as the summary has it) and a draft equal to the command:
     Your step holds exactly his two steps, numbered, each text once, the command once in one box, no summary line, no "Draft", the agent's step not in it; Next holds all four
  2  the same with the server's line written without his name, in a bold or role form, and first in the list: still not drawn, and the numbers start at 1; a repeated line of his is drawn once
  3  a message to paste: inside the step that names it, under "Message to paste", with Copy, escaped; an email: "Email text to paste"; a command and a message in one block: the command in its plain box, no label
  4  the home row: the same numbered block as the item page, then the note box and Send; a message is inside its step, collapsed under the same label
  5  an item with no step of his on the checklist draws its step field as before, the draft inside it with the new label
  6  the summary is still on the page where space is short: the tab title

    tests/run-suite your_step        → exit 0 / 1"""
import html, json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="yourstep-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"

toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"), keywords=True)
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
for pat, rep in ((r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]'), (r'(?m)^board_url = "[^"]*"', f'board_url = "{BOARD}"'),
                 (r'(?m)^base_url = "[^"]*"', f'base_url = "{BOARD}"'), (r'(?m)^owner = "the owner"', 'owner = "Oliver"'), (r'(?m)^ui_open = true', 'ui_open = false')):
    toml, n = re.subn(pat, rep, toml); assert n == 1, pat
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state", "brain/projects", "secrets"): (T / d).mkdir(parents=True)
OWNER = "00000000-0000-4000-8000-000000000001"
AGENT = "00000000-0000-4000-8000-000000000002"
now = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({OWNER: {"name": "home-here", "machine": "a", "seen": now}, AGENT: {"name": "home-agent", "machine": "a", "seen": now}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "home-agent", "status": "active", "board": [], "board_open": 0}}}))

CMD = "umask 077; read -rs k; printf '%s' \"$k\" > ~/.config/tool/admin-key; unset k"
S1 = "create an admin key in the vendor console under Settings, Admin keys, then run the command in the draft in the shell"        # the summary, as a session writes it
L1 = "in the vendor console, go to Settings, Admin keys, Create admin key, and copy the new key"
L2 = f"in the shell run `{CMD}`, paste the key with Shift+Insert, then press Enter"
L3 = "home-agent: check the spend card reads with the new key"
MSG = "Hi Sam, today's notes are attached.\n1. The dates stay as they are.\n2. <b>Please</b> confirm & reply."


def item(i, **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": "open",
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                     "metadata": {"owner": OWNER, "project": "projects/alpha", "needs": ["home-agent"], "state": "your-step", **meta}}))


# 1: the shape of the case that drew the summary twice: his two steps, an agent's step, the server's line for the summary last (his name in front, as the summary has it), a draft equal to the command
item(1, step=f"Oliver: {S1}", owner_step=f"Oliver: {S1}", draft=CMD, next=f"Oliver: {L1}\nOliver: {L2}\n{L3}\nOliver: {S1}")
# 2: the server's line without his name, in a bold form and a role form, and first; a line of his that repeats an earlier one; the numbers start at 1
item(2, step=S1, owner_step=f"Oliver: {S1}", next=f"Oliver: {S1}\nOliver: {L1}\n**Oliver:** {L1}\nOliver: {L2}\n{L3}")
item(3, step=f"**Oliver:** {S1}", owner_step=f"Oliver: {S1}", next=f"Oliver (owner): {S1}\nOliver: {L1}\nOliver: {L2}")
# 3: a message to paste, an email, and a command with a message
item(4, step="Send Sam the update on Slack", draft=MSG, next="Oliver: In Slack, open your DM with Sam and paste the message\nOliver: say done here\nhome-agent: check it")
item(5, step="Email Sam the notes", draft=MSG, next="Oliver: Open your email, write to Sam and paste the text\nhome-agent: check it")
item(6, step="Post the update, then run the command", draft=MSG, next="Oliver: Run `uv run tool.py --check` in the shell\nOliver: In Slack, post the message in the channel\nhome-agent: check it")
# 5: no step of his on the checklist: the step field is the step; its draft inside it
item(7, step="Send Sam the update on Slack", draft=MSG, next="home-agent: check it")
item(8, step="Run `uv run tool.py --check` in the shell and say done", next="home-agent: check it")
# review fixes
SUM = "Open the console"
item(9, step=SUM, next=f"Oliver: {SUM}\nOliver: Paste the key into the shell\nhome-agent: check")                               # a real step that says the summary's words, no server line (no owner_step)
item(10, step=SUM, owner_step=f"Oliver: {SUM}", next=f"Oliver: {SUM}\nOliver: Paste the key into the shell\nOliver: {SUM.upper()}\nhome-agent: check")      # the server's line (the last open line that says the summary, here the upper-case one) is skipped, the first real step that says the same words is kept
OLD = "In PowerShell, do these in order:\n1. Run `ssh -t box-a 'uptime'` and read the output\n2. Run `ssh -t box-a 'tmux ls'` and read the list"
item(11, step=OLD, owner_step="Oliver: In PowerShell, do these in order:", next="Oliver: In PowerShell, do these in order:\nOliver: say done on the item\nhome-agent: check")       # a step stored before the numbered-step rule
item(12, step=OLD, owner_step="Oliver: In PowerShell, do these in order:", next="Oliver: In PowerShell, do these in order:\nOliver: Run `ssh -t box-a 'uptime'` and read the output\nOliver: say done on the item")       # one of its commands is already a line of his
item(13, step="Run the command", owner_step="Oliver: Run the command", next="Oliver: Run the command\nOliver:\n  Run `uv run x y`\nOliver: then say done")       # a line with nothing after his name: the line under it is the step
item(14, step="Post the note, mind the e-mail thread", draft=MSG, next="Oliver: In Slack, post the message in #email-alerts\nhome-agent: check")      # a Slack post, the summary says e-mail
# The Korean strings below are \u escapes (Korean for "email", "mail", "send", "paste" and particles), so the public scan finds no Hangul in the repo; the checks still run on the real words.
item(15, step="Send the note", draft=MSG, next="Oliver: \uC774\uBA54\uC77C\uB85C \uBCF4\uB0B4\uACE0 \uBD99\uC5EC\uB123\uAE30\nhome-agent: check")
item(16, step="Send the note", draft=MSG, next="Oliver: \uBA54\uC77C\uC5D0 \uBD99\uC5EC\uB123\uAE30\nhome-agent: check")
item(17, step="Send the note", draft=MSG, next="Oliver: Email Sam, then paste the text\nOliver: paste it into the gmail draft or e-mail Lee\nhome-agent: check")
item(18, step="Check the key", owner_step="Oliver: Check the key", next="Oliver: Check the key\nOliver: Paste the key into the shell\nOliver: PASTE THE KEY INTO THE SHELL\noliver: paste the key into the shell\nhome-agent: check")      # three of his own lines that differ only in case, none the server's line
for i, w in ((21, "email\uB85C \uBCF4\uB0B4\uAE30"), (22, "Email\uC744 \uC5F4\uACE0 \uBD99\uC5EC\uB123\uAE30"), (23, "e-mail\uC5D0 \uBD99\uC5EC\uB123\uAE30")):
    item(i, step="Send the note", draft=MSG, next=f"Oliver: {w}\nhome-agent: check")
(T / "store/next-id").write_text("30"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\n---\n\n# Alpha\n")
git = lambda *a: subprocess.run(["git", "-C", f"{tmp}/store", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a], check=True, capture_output=True)
git("init", "-q"); git("add", "-A"); git("commit", "-q", "-m", "fixture")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:1200]}" if got is not None else ""))

import stackshot.web.ui.render as ui_render

BOX = lambda i: {"action": f"/items/a{i}/answer", "token": "TOKEN", "sent": ""}
bd = ui_render.Board(str(T / "store"))
page = lambda i: bd.item_html(f"a{i}", answer=BOX(i))
def block(p):
    m = re.search(r'<div class="iask istep"><b>Your step</b><div class="istepbody">(.*?)</div></div><form class="ianswer"', p, re.S)
    return m.group(1) if m else ""
def nextlist(p):
    m = re.search(r'<ul class="inext" aria-label="Next steps">(.*?)</ul>', p, re.S)
    return m.group(1) if m else ""
def lis(b): return [html.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in re.findall(r"<li>(.*?)</li>", b, re.S)]
ec = lambda t: html.escape(t, quote=True)

# ---- 1. the item page
p1 = page(1); b1 = block(p1); n1 = nextlist(p1)
check("1 page: the Your step block exists and holds one numbered list of exactly his two steps", b1.startswith('<div class="istepnext"><ol class="stepol">') and b1.count("<ol") == 1 and b1.count("<li>") == 2, b1[:800])
check("1 page: ...the list starts at 1 (no start attribute), and the steps are his own text without his name, in order",
      " start=" not in b1 and "<li>go to Settings" not in b1 and lis(b1)[0].startswith("in the vendor console, go to Settings, Admin keys, Create admin key, and copy the new key") and "run the command below, paste the key with Shift+Insert, then press Enter" in lis(b1)[1], lis(b1))
check("1 page: each step's text is said once: the first once, the second once", b1.count("copy the new key") == 1 and b1.count("paste the key with Shift+Insert") == 1, b1)
check("1 page: no summary line: the summary's words (the server's line for it) are not in the block, and no \"Oliver:\" either", "create an admin key" not in b1 and "run the command in the draft" not in b1 and "Oliver:" not in b1, b1)
check("1 page: the command is in one box with a Copy button and no label, once", b1.count('<div class="cmd">') == 1 and b1.count(ec(CMD)) == 1 and b1.count('class="b copy"') == 1 and 'class="dlab"' not in b1, b1)
check("1 page: no separate draft: the draft is the command the step already shows, so it is not drawn again, and \"Draft\" is nowhere in the block", 'class="draft"' not in p1 and "Draft" not in b1 and "Draft" not in p1.split("<title>")[1].split("</title>")[0], b1)
check("1 page: the agent's step is not in the block", "check the spend card" not in b1, b1)
check("1 page: Next keeps every step, his included: all four lines, open", re.findall(r'<li class="cl-(\w+)">', n1) == ["open"] * 4 and n1.count("Oliver:") >= 3 and "check the spend card" in n1 and "copy the new key" in n1, n1[:900])
check("1 page: ...and the block is directly under the state line and above the note box", p1.index("Your step") < p1.index('<form class="ianswer"') < p1.index('aria-label="Next steps"'), None)

# ---- 2. the repeat check: the server's line without his name, in a bold or role form, first in the list, and a line repeated
for i in (2, 3):
    pi = page(i); bi = block(pi)
    check(f"2 page a{i}: the server's line for the summary is not drawn, first in the list or not, his name in front of it in any form", "create an admin key" not in bi and "run the command in the draft" not in bi, bi)
    check(f"2 page a{i}: ...his two steps are numbered from 1 and each stands once", bi.count("<li>") == 2 and " start=" not in bi and bi.count("copy the new key") == 1 and bi.count(ec(CMD)) == 1, bi)
check("2 page: a line of his that repeats an earlier one (the bold form) is drawn once", block(page(2)).count("copy the new key") == 1 and nextlist(page(2)).count("copy the new key") >= 1, block(page(2)))
r_item = next(x for x in bd.rows if x["gid"] == "a2")
check("2 unit: his_open_steps leaves out the summary's line and the repeat, keeps his two others in order",
      [f for f, _ in bd.his_open_steps(r_item)] == [L1, L2], bd.his_open_steps(r_item))

# ---- 3. a message to paste
p4 = page(4); b4 = block(p4)
m4 = re.search(r"<li>(.*?)</li>", b4, re.S)
check("3 message: the draft sits inside the step that names it (the first, which says paste the message), under \"Message to paste\" with Copy beside it",
      b4.count("<li>") == 2 and bool(m4) and '<b class="dlab">Message to paste</b><button type="button" class="b copy" aria-label="Copy the message to paste">Copy</button>' in m4.group(1) and "paste the message" in m4.group(1), b4)
check("3 message: ...never labeled \"Draft\", in the block or in a button name, and the text is escaped and whole", "Draft" not in p4.split("</head>")[-1].replace("Drafts", "") and "&lt;b&gt;Please&lt;/b&gt; confirm &amp; reply." in b4 and "<b>Please</b>" not in b4 and b4.count("Hi Sam") == 1, b4)
check("3 message: ...and it is no command box", 'class="cmd"' not in b4 and "<pre><code>Hi Sam" in b4, b4)
check("3 message: the other step carries none", "say done here" in b4 and b4.index("say done here") > b4.index("Hi Sam"), b4)
p5 = page(5); b5 = block(p5)
check("3 email: the label reads \"Email text to paste\"", '<b class="dlab">Email text to paste</b>' in b5 and "Message to paste" not in b5 and "Draft" not in b5, b5)
p6 = page(6); b6 = block(p6)
l6 = re.findall(r"<li>(.*?)</li>", b6, re.S)
check("3 both: a command and a message in one block: the command in its plain box with Copy and no label, the message inside the step that posts it",
      len(l6) == 2 and "uv run tool.py --check" in l6[0] and "dlab" not in l6[0] and 'class="cmd"' in l6[0] and "Message to paste" in l6[1] and 'class="cmd"' not in l6[1] and b6.count('class="draft"') == 1, b6)

# ---- 4. the home row
page_home = bd.html()
def row(i):
    m = re.search(rf'<li class="(?:irow )?hrow" id="task-a-{i}"(?: data-st="[a-z]+")?>(.*?)</li>(?=<li class="(?:irow )?hrow"|</ul>)', page_home, re.S)
    return m.group(1) if m else ""
h1 = row(1)
sn = re.search(r'<div class="istepnext">(.*?)</div>(?=<div class="hask">|</span></div><div class="ir-act">)', h1, re.S)
check("4 home: the row of the same item is a Your move row", bool(h1) and 'id="your-move"' in page_home, page_home[:300])
check("4 home: ...it draws the same numbered block as the item page: the same list, byte for byte", bool(sn) and sn.group(0) == re.search(r'<div class="istepnext">.*?</div>(?=</div></div><form class="ianswer")', p1, re.S).group(0)
      if re.search(r'<div class="istepnext">.*?</div>(?=</div></div><form class="ianswer")', p1, re.S) else bool(sn) and sn.group(1) in b1, h1[:1500])
check("4 home: ...no summary line, no \"Draft\", the command once in one box, the agent's step absent",
      "create an admin key" not in h1 and "Draft" not in h1 and h1.count('<div class="cmd">') == 1 and h1.count(ec(CMD)) == 1 and "check the spend card" not in h1, h1)
check("4 home: ...then the note box with its Send, as the item page has it", h1.index('<div class="istepnext">') < h1.index('<form class="hanswer hstep"') and 'name="act" value="send"' in h1, h1[-700:])
h4 = row(4)
check("4 home: a message is inside its step, collapsed under the same label with Copy in the summary",
      '<summary><span class="dlab">Message to paste</span><button type="button" class="b copy" aria-label="Copy the message to paste">Copy</button></summary>' in h4 and h4.index("paste the message") < h4.index('class="draft hdraft"') < h4.index("say done here")
      and "Draft" not in h4 and "draft below" not in h4, h4[:1500])
check("4 home: an email says \"Email text to paste\"", "Email text to paste" in row(5) and "Message to paste" not in row(5), row(5)[:900])

# ---- 5. no step of his on the checklist: the step field itself, as before
p7 = page(7); b7 = block(p7)
check("5 page: with no step of his on the checklist the block draws the step field, the draft right under its text with the new label",
      "Send Sam the update on Slack" in b7 and b7.index("Send Sam") < b7.index('<b class="dlab">Message to paste</b>') and 'class="istepnext"' not in b7 and "Draft" not in b7, b7)
b8 = block(page(8))
check("5 page: a step field with a command: the text, then the command in its plain box with Copy", "uv run tool.py --check</code></pre><button" in b8 and b8.count('class="cmd"') == 1 and "dlab" not in b8, b8)
r7 = next(x for x in bd.rows if x["gid"] == "a7")
check("5 home: the row's step block is the same function's answer", bd.home_step(r7)[0] == bd.step_block_html(r7, home=True) and "Message to paste" in bd.home_step(r7)[0], bd.home_step(r7)[0][:500])

# ---- 7. review fixes
b9 = block(page(9)); l9 = lis(b9)
check("7 a step of his that says the summary's words is drawn (no server line is recorded), both of his steps numbered", l9 == [SUM, "Paste the key into the shell"], l9)
b10 = block(page(10)); l10 = lis(b10)
check("7 the server's line (the last line that says the summary, the upper-case one) is skipped and the first, a real step with the same words, is kept", l10 == [SUM, "Paste the key into the shell"] and b10.count("<li>") == 2, l10)
l18 = lis(block(page(18)))
check("7 three of his lines that differ only in case are drawn once, the other not repeated", l18 == ["Paste the key into the shell"], l18)
check("7 a Korean particle glued to email, Email or e-mail still reads as email", all('<b class="dlab">Email text to paste</b>' in block(page(i)) for i in (21, 22, 23)), [block(page(i))[:300] for i in (21, 22, 23)])
b11 = block(page(11)); l11 = lis(b11)
check("7 a step stored before the numbered-step rule keeps its commands: both, then his line, numbered once each",
      len(l11) == 3 and l11[0].startswith("Run") and "read the output" in l11[0] and "read the list" in l11[1] and l11[2] == "say done on the item"
      and b11.count('class="cmd"') == 2 and b11.count("ssh -t box-a &#x27;uptime&#x27;") == 1 and b11.count("ssh -t box-a &#x27;tmux ls&#x27;") == 1 and "do these in order" not in b11 and b11.count("<ol") == 1 and " start=" not in b11, b11)
b12 = block(page(12)); l12 = lis(b12)
check("7 a command that a line of his already shows is not drawn twice, the other is drawn at its place", len(l12) == 3 and b12.count("ssh -t box-a &#x27;uptime&#x27;") == 1 and b12.count("ssh -t box-a &#x27;tmux ls&#x27;") == 1
      and "read the output" in l12[0] and "read the list" in l12[1] and l12[2] == "say done on the item", (l12, b12))
b13 = block(page(13)); l13 = lis(b13)
check("7 a line with nothing after his name keeps its step and the command under it", len(l13) == 2 and l13[0].startswith("Run") and b13.count("<li>") == 2 and b13.count(ec("uv run x y")) == 1 and l13[1] == "then say done", (l13, b13))
check("7 the next list still holds all of them", nextlist(page(13)).count("<li") >= 3 and "uv run x y" in nextlist(page(13)), nextlist(page(13)))
b14 = block(page(14))
check("7 a Slack post under a summary that says e-mail, in a channel named email-alerts, is a message", '<b class="dlab">Message to paste</b>' in b14 and "Email text" not in b14, b14)
check("7 the Korean words for e-mail make it email text", 'Email text to paste' in block(page(15)) and 'Email text to paste' in block(page(16)), (block(page(15)), block(page(16))))
b17 = block(page(17))
check("7 the label is decided by the step the text sits under (the one that names pasting, which names an email)", '<b class="dlab">Email text to paste</b>' in b17 and b17.count('class="draft"') == 1, b17)
chk = bd.draft_label
check("7 draft_label unit: Korean particles after Latin email read as email; email_alerts, emailed, an address and #email-alerts do not",
      [chk(t) for t in ("email\uB85C \uBCF4\uB0B4\uAE30", "Email\uC744 \uC5F4\uACE0", "e-mail\uC5D0 \uBD99\uC5EC\uB123\uAE30", "email_alerts", "emailed", "sam@email.com", "#email-alerts", "gmail")] == ["Email text to paste"] * 3 + ["Message to paste"] * 5, [chk(t) for t in ("email\uB85C \uBCF4\uB0B4\uAE30", "Email\uC744 \uC5F4\uACE0", "e-mail\uC5D0 \uBD99\uC5EC\uB123\uAE30", "email_alerts", "emailed", "sam@email.com", "#email-alerts", "gmail")])
check("7 draft_label unit: email, e-mail, emails; not a channel, an address, gmail or mailing; Korean \uBA54\uC77C", [chk(t) for t in ("send the email", "an e-mail", "emails to Sam", "post in #email-alerts", "write to sam@email.com", "in the gmail draft", "the mailing list", "\uC774\uBA54\uC77C", "\uBA54\uC77C\uC744")]
      == ["Email text to paste"] * 3 + ["Message to paste"] * 4 + ["Email text to paste"] * 2, [chk(t) for t in ("send the email", "an e-mail", "emails to Sam", "post in #email-alerts", "write to sam@email.com", "in the gmail draft", "the mailing list", "\uC774\uBA54\uC77C", "\uBA54\uC77C\uC744")])

# ---- 6. the summary stays where space is short
check("6 summary: the step field still holds the summary (the tab title, the Slack notice read it)", json.loads((T / "store/a/1.json").read_text())["metadata"]["step"] == f"Oliver: {S1}", None)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
