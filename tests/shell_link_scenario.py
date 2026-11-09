"""Scenario test for the machine a step's command runs on and the Open shell link — fixture data, no live store, no network, no server socket.

A command's copy box, in the Your step block (item page and home row) and anywhere else a command box is drawn, has a line above it that says where the command runs, and, for the owner who works in
sala's Shell, an "Open shell" link to the page that opens that shell. Stackshot holds no keys to any machine and has no shell of its own: this is a label and a link, nothing more.

With [steps] owner_shell = "sala-shell" the line says "Runs on <host>": the ssh target of an `ssh h '...'` or `ssh -t h ...` command, else [steps] bash_host. With "powershell" it says "In PowerShell",
and an ssh command still names its host. With "" nothing is named and no link is drawn. [steps] shell_url (an http(s) URL or a path starting with one "/") adds the link, for sala-shell only: one per
numbered step (on the first box of a step that holds two commands; one for the whole block when the step is not a numbered list), target _blank, rel noopener noreferrer, the address escaped. Any other value, and
a value set with an owner_shell other than sala-shell, draws no link and the config check (config.notes) names it. An ssh command whose host cannot be read ($HOST, $(...), a line continuation, an IPv6 scope)
names no machine (no fallback to the bash_host or PowerShell), and its link still shows in sala-shell. The label reads the first command line of a block, past blank lines and `#` comment lines.

  1  sala-shell with a bash_host and a shell_url: a plain command names the bash_host; `ssh h '...'` and `ssh -t h ...` name h; one link per step, two commands in a step still one link, a second step its own
  2  the ssh target is read past the options (-p 22, -o ..., user@host, quoted values, bundled flags such as -tl bob, ssh://u@h:2222) and is empty for a command that is not ssh, a `! ` line or a link;
     a host that cannot be read draws no machine label, a leading comment line is skipped
  3  shell_url unset: the machine is named and no link; owner_shell "" names nothing and draws nothing, whatever shell_url says; sala-shell with no bash_host draws the link and no name
  4  powershell: "In PowerShell" for a plain command, the ssh host for an ssh command, and no link
  5  shell_url that is not an address (javascript:, data:, ftp:, //host, a space, not a string): no link, and config.notes names it; a good one and an empty one add no note
  6  a URL with a quote and & in it is escaped in the href; a path starting with "/" is accepted
  7  the home row's Your move entry: the same lines, the same links
  8  link counts: three numbered steps with a command each -> 3 links; one step with two top-level fenced blocks and prose between -> 1; a text part then a fenced part -> 1; the same on the home row
  9  a shell_url with an owner_shell other than sala-shell: exactly one config note says it only applies with sala-shell

    tests/run-suite shell_link        → exit 0 / 1"""
import json, logging, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch
tmp = _scratch.mkdtemp(prefix="shelllink-"); T = pathlib.Path(tmp)
BOARD = "https://board.example.org"

toml = pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")
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
STEP = "Run the commands and say done"
def item(i, next_, step=STEP):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": "- A thing, finished when it works", "status": "open",
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600,
                                                     "metadata": {"owner": OWNER, "project": "projects/alpha", "needs": ["home-agent"], "state": "your-step", "step": step, "next": next_}}))
item(1, "Oliver: run `uv run tool.py --check` and read the output\nhome-agent: check it")                                      # a plain command
item(2, "Oliver: run `ssh other-host 'uptime'` and read the output\nhome-agent: check it")                                    # ssh, host first
item(3, "Oliver: run `ssh -t other-host uptime` and read the output\nhome-agent: check it")                                   # ssh -t
item(4, "Oliver: run `uv run a.py --x` then `uv run b.py --y`\nhome-agent: check it")                                         # two commands in one step
item(5, "Oliver: run `uv run a.py --x`\nOliver: then run `ssh other-host 'uptime'`\nhome-agent: check it")                    # two steps, a command each
item(6, "Oliver: run `uv run a.py --x`\nOliver: run `uv run b.py --y`\nOliver: run `uv run c.py --z`\nhome-agent: check it")                  # three numbered steps, a command each
item(7, "home-agent: check it", step="Run this:\n```\nuv run a.py --x\n```\nthen, on the second box:\n```\nuv run b.py --y\n```")             # not a numbered list: two top-level fenced blocks, prose between
item(8, "home-agent: check it", step="Run `uv run a.py --x` first\n```\nuv run b.py --y\n```")                                              # not a numbered list: a text part with a command, then a fenced part
item(9, "Oliver: run:\n```\nuv run a.py --x\n```\nOliver: then:\n```\nuv run b.py --y\n```\nhome-agent: check it")                          # two numbered steps, a fenced block under each
item(15, "home-agent: check it", step="1. run `uv run a.py --x`\n2. run `uv run b.py --y`")                                                 # a numbered list in the step field: a link per numbered step
item(10, "Oliver:\n```\nssh -t $HOST uptime\n```\nhome-agent: check it")                                                              # a host that is a variable
item(11, "Oliver:\n```\nssh $(pick-host) uptime\n```\nhome-agent: check it")                                                         # a host that is a command substitution
item(12, "Oliver:\n```\nssh -t \\\nh cmd\n```\nhome-agent: check it")                                                                   # a line continuation
item(13, "Oliver:\n```\nssh fe80::1%eth0 uptime\n```\nhome-agent: check it")                                                         # an IPv6 scope
item(14, "Oliver:\n```\n# restart it\nssh h cmd\n```\nhome-agent: check it")                                                        # a comment line, then ssh
item(16, "Oliver:\n```\n# systemctl restart x\nssh h ls\n```\nhome-agent: check it")                                                         # a root prompt line, then ssh
item(17, "Oliver:\n```\nssh -i \"~/my key h ls\n```\nhome-agent: check it")                                                              # a quote that never closes
item(18, "Oliver:\n```\nFOO=\"a b\" ssh h ls\n```\nhome-agent: check it")                                                               # an env prefix with a quoted value
item(19, "Oliver:\n```\nhttps://x.example.com/y\n```\n```\nuv run a.py --x\n```\nhome-agent: check it")                                          # a bare link box, then a command
item(20, "Oliver:\n```\n! sala x\n```\n```\nuv run a.py --x\n```\nhome-agent: check it")                                                          # a pane line box, then a command
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
from stackshot.core import config as C
from stackshot.model import step_commands as SC

STEPS = C.CFG["steps"]; WAS = dict(STEPS)         # the setting is read where it is used: a section flips it in the running config and the end puts it back
def conf(owner_shell, bash_host="example-host", shell_url=None):
    STEPS.clear(); STEPS.update(WAS)
    STEPS["owner_shell"] = owner_shell; STEPS["bash_host"] = bash_host
    if shell_url is None: STEPS.pop("shell_url", None)
    else: STEPS["shell_url"] = shell_url

URL = "https://shell.example.com/terminal"
LINK = f'<a class="cshell" href="{URL}" target="_blank" rel="noopener noreferrer">Open shell</a>'
BOX = lambda i: {"action": f"/items/a{i}/answer", "token": "TOKEN", "sent": ""}
bd = ui_render.Board(str(T / "store"))
def block(i):
    m = re.search(r'<div class="iask istep"><b>Your step</b><div class="istepbody">(.*?)</div></div><form class="ianswer"', bd.item_html(f"a{i}", answer=BOX(i)), re.S)
    return m.group(1) if m else ""
def row(i):
    m = re.search(rf'<li class="(?:irow )?hrow" id="task-a-{i}"(?: data-st="[a-z]+")?>(.*?)</li>(?=<li class="(?:irow )?hrow"|</ul>)', bd.html(), re.S)
    return m.group(1) if m else ""
places = lambda b: re.findall(r'<div class="cplace"><span>([^<]*)</span>', b)
links = lambda b: re.findall(r"<a [^>]*>Open shell</a>", b)

try:
    # ---- 1. sala-shell, a bash_host, a shell_url
    conf("sala-shell", shell_url=URL)
    b = {i: block(i) for i in range(1, 6)}
    check("1 the blocks are found", all(b.values()), {i: bool(v) for i, v in b.items()})
    check("1 a plain command: the box says it runs on the bash_host, one Open shell link", places(b[1]) == ["Runs on example-host"] and links(b[1]) == [LINK], b[1])
    check("1 ssh h '...': the host it logs in to, not the bash_host", places(b[2]) == ["Runs on other-host"] and "example-host" not in b[2] and links(b[2]) == [LINK], b[2])
    check("1 ssh -t h ...: the same", places(b[3]) == ["Runs on other-host"] and links(b[3]) == [LINK], b[3])
    check("1 the line sits right above its box and the link is on that line",
          re.search(r'<div class="cplace"><span>Runs on example-host</span>' + re.escape(LINK) + r'</div><div class="cmd"><pre>', b[1]) is not None, b[1])
    check("1 the link opens a new tab with noopener noreferrer", 'target="_blank"' in links(b[1])[0] and 'rel="noopener noreferrer"' in links(b[1])[0], links(b[1]))
    check("1 a step with two commands: both boxes name the machine, one link (on the first box)", places(b[4]) == ["Runs on example-host"] * 2 and len(links(b[4])) == 1
          and b[4].index("Open shell") < b[4].index("uv run b.py"), b[4])
    check("1 two steps with a command each: one link for each step", len(links(b[5])) == 2 and places(b[5]) == ["Runs on example-host", "Runs on other-host"], b[5])
    check("1 the Copy button is still in every box", all(v.count('class="b copy"') == v.count('<div class="cmd">') > 0 for v in b.values()), b[4])

    # ---- 2. the ssh target
    for cmd, want in (("ssh h 'uptime'", "h"), ("ssh -t h uptime", "h"), ("ssh -tt h uptime", "h"), ("ssh -p 22 user@h uptime", "h"), ("ssh -o StrictHostKeyChecking=no -i key h ls", "h"),
                      ("ssh -oBatchMode=yes h ls", "h"), ("ssh -p22 h", "h"), ("ssh 'h' x", "h"), ("FOO=1 ssh h x", "h"), ("ssh -- h x", "h"), ("ssh", ""), ("ssh -t", ""),
                      ("uv run x --y", ""), ("! ssh h x", ""), ("https://x.example.com/y", ""), ("ssh $(x) y", "")):
        check(f"2 ssh_target({cmd!r}) = {want!r}", SC.ssh_target(cmd) == want, SC.ssh_target(cmd))
    # the label reads the FIRST COMMAND line: blank lines and `#` comment lines above it are skipped, so a block that starts with a plain command is not ssh even when a later line is
    check("2 a fenced block is read by its first command line", SC.ssh_target("ssh h\nls") == "h" and SC.ssh_target("ssh h 'x'\nls") == "" and SC.ssh_target("ls\nssh h x") == "")
    check("2 a comment or blank line above the command is skipped", SC.ssh_target("# restart it\nssh h cmd") == "h" and SC.ssh_target("\n\n# a\n# b\nssh h x") == "h"
          and SC.ssh_target("# only a comment") == "" and SC.ssh_target("# note\nls\nssh h x") == "", SC.ssh_target("# restart it\nssh h cmd"))
    check("2 a `# cmd` root prompt is a command: it is not skipped, a prose comment above ssh still is",
          SC.command_line("# systemctl restart x") == "# systemctl restart x" and SC.command_line("# systemctl restart x\nssh h ls") == "# systemctl restart x"
          and SC.ssh_target("# systemctl restart x\nssh h ls") == "" and SC.ssh_target("# restart it\nssh h ls") == "h" and SC.command_line("# restart it\nls") == "ls"
          and SC.command_line("#systemctl x\nls") == "ls", (SC.command_line("# systemctl restart x\nssh h ls"), SC.ssh_target("# restart it\nssh h ls")))
    conf("sala-shell", shell_url=URL)
    check("2 runs_on: `# systemctl restart x` names the bash_host and has the shell; the same line with ssh h on the next line names no place (a later line logs in elsewhere); prose then ssh h names h",
          SC.runs_on("# systemctl restart x") == ("Runs on example-host", True) and SC.runs_on("# systemctl restart x\nssh h ls") == ("", True)
          and SC.runs_on("# restart it\nssh h ls") == ("Runs on h", True), (SC.runs_on("# systemctl restart x"), SC.runs_on("# systemctl restart x\nssh h ls"), SC.runs_on("# restart it\nssh h ls")))
    check("2 runs_on: an unclosed quote on an ssh command names no place (no bash_host) and keeps the shell; a quoted env value reads its host",
          SC.runs_on('ssh -i "~/my key h ls') == ("", True) and SC.runs_on("ssh -o 'A b h ls") == ("", True) and SC.runs_on("FOO='a b' ssh h ls") == ("Runs on h", True)
          and SC.runs_on('FOO=1 BAR="x y" ssh h ls') == ("Runs on h", True), (SC.runs_on('ssh -i "~/my key h ls'), SC.runs_on("FOO='a b' ssh h ls")))
    check("2 runs_on: wrapped ssh names no place (never the bash_host) and keeps the shell; scp and ssh-keygen keep the bash_host; /usr/bin/ssh h reads h",
          all(SC.runs_on(c) == ("", True) for c in ("sudo ssh h", "env X=1 ssh h", "time -p ssh h", "cmd && ssh h", "echo | ssh h cat", "ssh -- -evil"))
          and SC.runs_on("/usr/bin/ssh h") == ("Runs on h", True) and all(SC.runs_on(c) == ("Runs on example-host", True) for c in ("scp a h:b", "ssh-keygen -t x", "ssh-copy-id h")),
          [(c, SC.runs_on(c)) for c in ("sudo ssh h", "cmd && ssh h", "/usr/bin/ssh h", "scp a h:b", "ssh-keygen -t x")])
    # The rule: a box whose text has an ssh-like word (ssh, ssh.exe, autossh, mosh; comments and quoted strings count) names a machine only when its first command line starts with ssh itself and the host is read;
    # a box with no such word keeps the default label unless a line starts with a word that is not plain. A missing label on a command that merely mentions ssh is accepted.
    KEEP = ("uv run x", "FOO=1 uv run x", ".\\x.ps1", "C:\\x\\y.exe a", "docker run \\\n  --rm img", "ls -la \\\n  /tmp", "scp a h:b", "ssh-keygen -t x", "ssh-copy-id h", "sudo ssh-keygen -A", "ssh-keyscan h", "ssh-add -l", "sshd -t", "docker ps", "bash script.sh", "cat ~/.ssh/config",
            "echo hi |", "echo hi\nsystemctl restart x", "# restart it\nsystemctl restart x", "# systemctl restart x", "FOO=$(x) uv run y", "if x; then y; fi", "echo " + "a" * 300000)
    NONE = (  # an ssh-like word and the first command is not ssh: wrappers, pipes, separators, shells, containers, tmux, tools the code does not know
            "sudo ssh h", "env X=1 ssh h", "cmd && ssh h", "cmd; ssh h", "cmd&&ssh h", "echo | ssh h cat", "echo x | /usr/bin/ssh h cat", "sshpass -p x ssh h", "sshpass ssh h",
            "bash -c 'ssh h'", 'sh -c "ssh h ls"', "eval ssh h", "if ssh h; then x; fi", "{ ssh h; }", "while true; do ssh h; done", "for h in a b; do ssh $h uptime; done", "echo `ssh h`",
            "docker exec c ssh h", "kubectl exec x -- ssh h", "parallel ssh {} ::: a b", "ssh-agent bash -c 'ssh h'", "autossh h", "mosh h", "script -c 'ssh h'", "tmux new 'ssh h'",
            "sudo -u bob ssh h", "sudo -E ssh h", "docker exec -it c ssh h", "echo $(ssh h)", "bash -lc 'cd x && ssh h'", "docker compose exec svc ssh h", "tmux send-keys 'ssh h' Enter",
            "tailscale ssh h", "gcloud compute ssh h", "vagrant ssh", "docker run -v x:y img ssh h", "sudo --user bob ssh h", "sudo -Eu bob ssh h", "time -p ssh h", "runuser -l u -c 'ssh h'",
            "oc exec p -- ssh h", "lxc exec c -- ssh h", "fish -c 'ssh h'", "xterm -e ssh h", "screen ssh h", 'tmux send "ssh h" Enter', "sudo ssh.exe h", "foo C:\\x\\ssh.exe h", "foo /usr/bin/ssh h",
            "ls && ssh h", "ls; ssh h", "ls > o; ssh h", "(ssh h)", 'echo "$(ssh h)"', 'echo "`ssh h`"', "cat <(ssh h cat x)", "diff x >(ssh h cat)", "echo $(sudo ssh h)",
            # the review's inputs: a continued first line, a substitution in quotes, a # inside a word, a script that runs ssh, a variable or expansion as the command
            "ls \\\nsudo -u bob ssh h", 'echo "$(cat f | ssh h)"', "echo x#y | ssh h", """awk 'BEGIN{system("ssh h id")}'""", "$SSH h", "ssh${IFS}h", '"ssh" h', "s''sh h",
            # a command that only mentions ssh: no label (accepted)
            "sudo systemctl restart ssh", "sudo ufw allow ssh", "sudo apt install ssh", "sudo journalctl -u ssh -n 50", "sudo ls /etc/ssh", "time make ssh", "command -v ssh", "watch echo ssh",
            'git commit -m "fix; ssh config"', 'echo "hello && ssh h"', 'grep "foo|ssh " file', "env | grep ssh", "echo ssh h", "ls ssh", "make ssh", "tmux attach -t ssh", "tmux new -s ssh",
            "docker exec c cat ssh", "type ssh", "which ssh", "rsync -e ssh a h:b", "cat /etc/ssh/sshd_config", "ls /etc/ssh", "systemctl status ssh \\", 'echo "unclosed ssh', "echo " + "a" * 300000 + " ssh",
            "a" * 300000 + " ssh h",
            # a line of the box outside the first, or a comment, that has ssh in it
            "ls\nssh h x", "# systemctl restart x\nssh h ls", "echo hi\nsystemctl restart ssh", "echo hi\nsudo ssh h", "echo hi\n\nls && ssh h", "systemctl status x\nautossh h", "ls\n# then ssh h\ncat x",
            "echo hi |\nssh h cat", "echo hi \\\nssh h", "cmd \\\n ssh h", "uv run x\nssh h",
            # a # prompt line that starts with ssh is no command
            "# ssh to the server\nls", "# ssh h", "# ssh h ls",
            # ssh first but the host cannot be read: a redirection, a query, an unclosed quote, a variable, a missing host
            "ssh 2>&1 h", "ssh >out h", "ssh -t 2>&1 h", "ssh -G h", "ssh -V", "ssh -Q cipher", "ssh -i 'a b h", 'ssh -i "a b h', "ssh -- -evil", "ssh -t $HOST uptime", "ssh $(pick) uptime", "ssh", "ssh -t",
            # a line that starts with a word that is not plain may build any command
            "$CMD x", "`which x` y", "{ls,x}", "*x y", "l\"s\" x", "FOO=1 $X y", "uv run x\n$CMD y", "if $X; then y; fi", "ls${x} y", "ls\n\n  ?x y",
            # an ssh with a remote command or a chain, then more command lines: they run locally, so the box is not on h (a script inside an open quote or heredoc is the remote's)
            "ssh h 'systemctl stop x'\nsystemctl start y", "ssh h id\nls", "ssh h; ls\nid", "ssh h;\nls", "ssh h &&\n ssh g", "ssh h ls\n$CMD", "ssh h && ls\nid", "ssh h|cat\nls",
            "ssh -f -N -L 1:2:3 h\ncurl localhost:1", "ssh -fN -L 1:2:3 h\nls", "ssh -N h\nls", "ssh h '\n uptime\n'\nls", "ssh h <<EOF\nx\nEOF\nls", "ssh h <<-EOF\nx\nEOF\nls", "ssh h <<'EOF'\nx\nEOF\nls",
            "ssh h bash <<EOF\nx\nEOF\nls", "ssh h; ls <<EOF\nx\nEOF", "ssh h \\\n  ls\nid", "ssh h 2>&1\nls", "ssh h # note\nls", "ssh h 'a'\n# systemctl restart x",
            # a backslash inside the first word hides ssh; so does a first line that is one word ending in a backslash
            "s\\sh h", "ss\\h h", "\\slogin h", "ss\\\nh h", "\\ssh h", "ss\\\nh h\nls", "uv run x\ns\\sh h",
            # slogin, plink and dbclient are ssh-like words
            "slogin h", "plink h", "dbclient h", "plink.exe h", "echo hi\nslogin h", "sudo plink h", "sudo dbclient h",
            # a redirection or a separator among the words before the host would shift it: unreadable
            "ssh -l 2>err bob h", "ssh -p 2>/dev/null 22 h", "ssh -l 2> err bob h", "ssh -p &>x 22 h", "ssh -t 2>/dev/null h", "ssh -t; h x", "ssh -l '2>err' bob h", "ssh -i k>x h",
            # a second ssh in a chain logs in elsewhere (the one-line forms), also after the quote of a multi-line command closes; a quoted ssh word after the separator counts too
            "ssh box1 'ls' && ssh box2 'ls'", "ssh box1 id | ssh box2 'cat > f'", "ssh box1 'tar c .' | ssh box2 'tar x'", "ssh box1 id; ssh box2 id", "ssh h && bash -c 'ssh g'", "ssh h 2>&1 | ssh g cat",
            "ssh h '\nuptime\n' && ssh g", "ssh h &&\nssh g", "ssh h && ssh g",
            # a HostName option sets the machine the login goes to: the word after the options is not it
            "ssh -o HostName=box2 box1 id", "ssh -oHostName=box2 box1 id", "ssh -o hostname=box2 box1 id", "ssh -o 'HostName box2' box1 id", "ssh -tohostname=x box1", "ssh -o HOSTNAME=x box1")
    READ = (  # an ssh command as the first command line, its host read; later lines are not read
            "/usr/bin/ssh h", "./ssh h", "FOO=1 ssh h ls", "ssh -J jump h", "ssh ssh://u@h:2222 ls", "ssh h 'a; ssh g'", "time ssh h", "exec ssh h", "ssh.exe h", "C:\\Windows\\ssh.exe h",
            "ssh h;", "ssh h|cat", "ssh h # note", "ssh h '\n uptime\n'", "ssh -t h '\n x\n'", "ssh h\nssh g", "ssh h\nsudo ssh g", "ssh h \\\n  ls", "ssh -P tag h", "ssh -E log -p 22 h",
            "ssh h 2>&1", "ssh h <<EOF\nssh g\nEOF", "ssh h '\n ssh g\n sudo ssh k\n'", "ssh -t h 'a\nb ssh c\n'", "ssh h '\n$CMD x\n'",
            # ssh h alone is an interactive login: the later lines are typed into it. A remote script (open quote, heredoc body, continued line) is inside the command; a chain or a remote command with nothing after it
            "ssh h\nls", "ssh h\nsystemctl start y", "ssh h 'uptime'", "ssh h && systemctl start y", "ssh h; ls", "ssh h <<EOF\nx\nEOF", "ssh h <<-EOF\nx\nEOF", "ssh h <<'EOF'\nx\nEOF", "ssh h bash -s <<'EOF'\nx\nEOF",
            "ssh h '\nuptime\nls", "ssh h '\n a; b\n'", "ssh h 'a'\n\n# note", "ssh -t h\nid", "ssh h\n\n", "ssh h id\n# note",
            # a chain with no second ssh keeps h; other -o options and a quoted ssh inside the first command's remote command do not move it
            "ssh h; ssh-keygen -A", "ssh h '\nuptime\n' && ls", "ssh h 'a; ssh g' && ls", "ssh -o StrictHostKeyChecking=no h id", "ssh -oBatchMode=yes h", "ssh -o User=bob h", "ssh -o ProxyJump=j h", "ssh -o 'User bob' h")
    check("2 no ssh-like word: the default label (the bash_host) and the shell", all(SC.runs_on(c) == ("Runs on example-host", True) for c in KEEP) and all(SC.ssh_target(c) == "" for c in KEEP),
          [(c[:40], SC.runs_on(c)) for c in KEEP if SC.runs_on(c) != ("Runs on example-host", True)])
    check("2 an ssh-like word and a first command that is not ssh with a readable host, or a command that may build one: no machine label, the shell kept and no host", all(SC.runs_on(c) == ("", True) for c in NONE)
          and all(SC.ssh_target(c) == "" for c in NONE), [(c[:40], SC.runs_on(c)) for c in NONE if SC.runs_on(c) != ("", True)])
    check("2 an ssh first command reads its host, whatever follows it", all(SC.runs_on(c) == ("Runs on h", True) for c in READ) and all(SC.ssh_target(c) == "h" for c in READ),
          [(c[:40], SC.runs_on(c)) for c in READ if SC.runs_on(c) != ("Runs on h", True)])
    import time as _time
    _t0 = _time.time()
    check("2 a word over 20000 characters is read fast and the same way", SC.runs_on("ssh h " + "a" * 300000) == ("Runs on h", True) and _time.time() - _t0 < 3, _time.time() - _t0)
    for cmd, want in (("ssh -o 'StrictHostKeyChecking no' other-host uptime", "other-host"), ('ssh -i "~/my key" h ls', "h"), ('ssh -o "ProxyCommand ssh jump -W %h:%p" h ls', "h"),
                      ("ssh -tl bob h", "h"), ("ssh -tp 22 h", "h"), ("ssh ssh://u@h:2222 ls", "h"), ("ssh ssh://h ls", "h"), ("ssh ssh://u@[::1]:22 ls", "[::1]"), ("ssh -tl", ""),
                      ("ssh -t $HOST uptime", ""), ("ssh $(pick) uptime", ""), ("ssh -t \\\nh cmd", ""), ("ssh fe80::1%eth0 uptime", ""), ("ssh -o 'unterminated h x", ""),
                      # a quote that never closes: the words cannot be told apart, so no host is read (never `key` or `b`)
                      ('ssh -i "~/my key h ls', ""), ("ssh -o 'A b h ls", ""),
                      # a VAR=value prefix, whatever the value holds
                      ('FOO="a b" ssh h ls', "h"), ("FOO='a b' ssh h ls", "h"), ('FOO=1 BAR="x y" ssh h ls', "h"), ("FOO=1 ssh h ls", "h"), ('FOO="a b" BAR=2 ssh -t u@h ls', "h"),
                      # ssh run by something else: it is ssh and no host is read; a program whose name only starts with ssh is no ssh session
                      ("/usr/bin/ssh h ls", "h"), ("./ssh h ls", "h"), ("sudo ssh h", ""), ("env X=1 ssh h", ""), ("time ssh h", "h"), ("cmd && ssh h", ""), ("cmd; ssh h", ""), ("cmd&&ssh h", ""),
                      ("echo | ssh h cat", ""), ("echo x | /usr/bin/ssh h cat", ""), ("scp a h:b", ""), ("ssh-keygen -t ed25519", ""), ("ssh-copy-id h", ""), ("echo ssh h", ""),
                      # a host that starts with - is no host; a trailing newline is no part of one
                      ("ssh -- -evil", ""), ("ssh -- u@-evil x", ""), ('ssh "h\n" x', ""),
                      # a `# ` line that starts with ssh is no ssh command
                      ("# ssh h ls", "")):
        check(f"2 ssh_target({cmd!r}) = {want!r}", SC.ssh_target(cmd) == want, SC.ssh_target(cmd))
    check("2 a pane line and a bare link name no place and no shell", SC.runs_on("! ssh h x") == ("", False) and SC.runs_on("https://x.example.com/y") == ("", False),
          (SC.runs_on("! x y"), SC.runs_on("https://x.example.com/y")))

    # ---- 3. shell_url unset, owner_shell "", no bash_host
    conf("sala-shell")
    check("3 shell_url unset: the machine is named, no link", places(block(1)) == ["Runs on example-host"] and not links(block(1)) and "cshell" not in block(1), block(1))
    conf("sala-shell", shell_url="")
    check("3 shell_url empty: no link", places(block(1)) == ["Runs on example-host"] and "cshell" not in block(1), block(1))
    conf("", shell_url=URL)
    check("3 owner_shell empty: nothing is named and no link, whatever shell_url says",
          all("cplace" not in block(i) and "cshell" not in block(i) and "Open shell" not in block(i) for i in range(1, 6)), block(2))
    check("3 ...and the box is the plain one", '<div class="cmd"><pre><code>uv run tool.py --check</code></pre>' in block(1), block(1))
    check("3 ...also on the home row", all(x not in row(2) for x in ("cplace", "Open shell")) and bool(row(2)), row(2))
    conf("sala-shell", bash_host="", shell_url=URL)
    check("3 sala-shell with no bash_host: a plain command names no machine and still has the link; an ssh command names its host",
          places(block(1)) == [] and links(block(1)) == [LINK] and "Runs on" not in block(1) and places(block(2)) == ["Runs on other-host"], (block(1), block(2)))

    # ---- 4. powershell
    conf("powershell", shell_url=URL)
    check("4 powershell: a plain command says In PowerShell", places(block(1)) == ["In PowerShell"], block(1))
    check("4 powershell: an ssh command still names its host, in both forms",
          places(block(2)) == ["Runs on other-host"] and places(block(3)) == ["Runs on other-host"] and "In PowerShell" not in block(2), (block(2), block(3)))
    check("4 powershell: no Open shell link, even with a shell_url", all("Open shell" not in block(i) and "cshell" not in block(i) for i in range(1, 6)), block(1))
    check("4 powershell: two commands each say In PowerShell", places(block(4)) == ["In PowerShell"] * 2, block(4))

    # ---- 5. a shell_url that is not an address
    def notes_for(v):
        cfg = {**C.CFG, "steps": {**WAS, "owner_shell": "sala-shell", "shell_url": v}}
        return [n for n in C.notes(cfg) if "shell_url" in n]
    for v in ("javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,<b>x</b>", "ftp://shell.example.com/x", "//evil.example.com/x", "shell.example.com/terminal", "https://", "https:///x",
              "https://shell.example.com/a b", "/a b", "mailto:a@example.com",
              "https://u:p@shell.example.com/t", "https://user@shell.example.com/t", "https://:p@shell.example.com/t", "https://shell.example.com:0/t", "https://shell.example.com:70000/t",
              "https://shell.example.com:abc/t", "http://[::1]:0/t", 42, True, ["https://shell.example.com"]):
        conf("sala-shell", shell_url=v)
        check(f"5 shell_url {v!r}: no link on the page and the config check names it",
              "cshell" not in block(1) and "Open shell" not in block(1) and C.shell_url() == "" and len(notes_for(v)) == 1 and "shell_url" in notes_for(v)[0], (block(1)[:300], notes_for(v)))
    for v in (URL, "/shell", "http://shell.example.com:8080/t?x=1", "https://shell.example.com:8443/t", "https://[::1]:8443/t", "https://[::1]/t", "https://shell.example.com:65535/", "", None):
        check(f"5 shell_url {v!r}: the config check says nothing", notes_for(v) == [], notes_for(v))
    STEPS.clear(); STEPS.update(WAS)
    check("5 the example config itself adds no note", not [n for n in C.notes() if "shell_url" in n], [n for n in C.notes() if "shell_url" in n])
    check("5 the notes line says what to write", "https://shell.example.com/terminal" in notes_for("javascript:x")[0] and "no Open shell link" in notes_for("javascript:x")[0], notes_for("javascript:x"))

    # ---- 6. escaping and a path
    ugly = 'https://shell.example.com/t?a=1&b="x"&c=\'y\'<z>'
    conf("sala-shell", shell_url=ugly)
    bu = block(1)
    check("6 a URL with a quote, & and angle brackets is escaped in the href and never raw",
          'href="https://shell.example.com/t?a=1&amp;b=&quot;x&quot;&amp;c=&#x27;y&#x27;&lt;z&gt;"' in bu and '&b="x"' not in bu and "<z>" not in bu and len(links(bu)) == 1, bu)
    conf("sala-shell", shell_url="/shell")
    check("6 a path starting with / is accepted", links(block(1)) == ['<a class="cshell" href="/shell" target="_blank" rel="noopener noreferrer">Open shell</a>'], block(1))
    conf("sala-shell", bash_host="a<b>&c", shell_url=URL)
    check("6 the machine name is escaped too", "Runs on a&lt;b&gt;&amp;c" in block(1) and "<b>" not in block(1), block(1))

    # ---- 7. the home row
    conf("sala-shell", shell_url=URL)
    r = {i: row(i) for i in (1, 2, 4, 5)}
    check("7 home: the rows are found", all(r.values()), {i: bool(v) for i, v in r.items()})
    check("7 home: a plain command names the bash_host, one link", places(r[1]) == ["Runs on example-host"] and links(r[1]) == [LINK], r[1][:900])
    check("7 home: an ssh command names its host, one link", places(r[2]) == ["Runs on other-host"] and links(r[2]) == [LINK], r[2][:900])
    check("7 home: a step with two commands has one link", places(r[4]) == ["Runs on example-host"] * 2 and len(links(r[4])) == 1, r[4][:1200])
    check("7 home: two steps, a link each", len(links(r[5])) == 2, r[5][:1200])
    conf("sala-shell")
    check("7 home: no shell_url, no link", "Open shell" not in row(1) and places(row(1)) == ["Runs on example-host"], row(1)[:600])
    conf("powershell", shell_url=URL)
    check("7 home: powershell says In PowerShell and has no link", places(row(1)) == ["In PowerShell"] and "Open shell" not in row(1), row(1)[:600])
    conf("", shell_url=URL)
    check("7 home: owner_shell empty draws neither", "cplace" not in row(1) and "Open shell" not in row(1), row(1)[:600])

    # ---- 3b. an ssh command whose host cannot be read: no machine label, no fallback, the link stays (sala-shell)
    conf("sala-shell", shell_url=URL)
    for i, what in ((10, "$HOST"), (11, "$(...)"), (12, "a line continuation"), (13, "an IPv6 scope")):
        bi = block(i)
        check(f"3b {what}: the box is drawn, no machine label (not the bash_host), the link is there", bool(bi) and 'class="cmd"' in bi and places(bi) == [] and "Runs on" not in bi
              and "In PowerShell" not in bi and links(bi) == [LINK], bi)
        check(f"3b {what}: the same on the home row", places(row(i)) == [] and links(row(i)) == [LINK], row(i)[:900])
    conf("powershell", shell_url=URL)
    check("3b powershell: an ssh command with no readable host does not say In PowerShell", all("In PowerShell" not in block(i) for i in (10, 11, 12, 13)), block(10))
    conf("sala-shell", shell_url=URL)
    check("3b a comment line, then ssh h cmd: the label reads host h", places(block(14)) == ["Runs on h"] and links(block(14)) == [LINK], block(14))

    check("3b a `# cmd` root-prompt line above ssh h: the first line is a command and a later line logs in to h, so the box names no machine (never h or the bash_host); the link stays",
          places(block(16)) == [] and "Runs on" not in block(16) and links(block(16)) == [LINK], block(16))
    check("3b an unclosed quote: no machine label (not key, not the bash_host), the link stays", places(block(17)) == [] and links(block(17)) == [LINK] and "Runs on" not in block(17), block(17))
    check("3b an env prefix with a quoted value: the host is read", places(block(18)) == ["Runs on h"] and places(row(18)) == ["Runs on h"], (block(18), row(18)[:600]))

    # ---- 8. how many links
    check("8 three numbered steps with a command each: 3 links, one on each step's first box", len(links(block(6))) == 3 and len(places(block(6))) == 3
          and all(len(re.findall(r"Open shell", li)) == 1 for li in re.findall(r"<li>.*?</li>", block(6), re.S)), block(6))
    check("8 one step with two top-level fenced blocks and prose between: 1 link, on the first box", len(links(block(7))) == 1 and len(places(block(7))) == 2
          and block(7).index("Open shell") < block(7).index("uv run a.py") and block(7).index("uv run a.py") < block(7).index("on the second box"), block(7))
    check("8 a text part with a command, then a fenced part: 1 link", len(links(block(8))) == 1 and len(places(block(8))) == 2
          and block(8).index("Open shell") < block(8).index("uv run b.py"), block(8))
    check("8 two numbered steps with a fenced block each: 2 links", len(links(block(9))) == 2 and len(places(block(9))) == 2, block(9))
    check("8 a numbered list in the step field: 2 links, one per numbered step", len(links(block(15))) == 2 and len(places(block(15))) == 2, block(15))
    for i, want in ((6, 3), (7, 1), (8, 1), (9, 2), (15, 2)):
        check(f"8 home row, item a{i}: {want} link(s)", len(links(row(i))) == want and len(places(row(i))) >= want, row(i)[:1500])
    conf("sala-shell")
    check("8 no shell_url: no link on any of them", all("Open shell" not in block(i) for i in (6, 7, 8, 9)))

    # ---- 8b. the link goes on the first box that can carry one
    conf("sala-shell", shell_url=URL)
    out = ui_render._cmd_blocks(["https://x.example.com/y", "uv run a"]); out2 = ui_render._cmd_blocks(["! sala x", "uv run a", "uv run b"])
    check("8b a bare link first: no link on it, the link on the next box", out.count("Open shell") == 1 and out.index("Open shell") > out.index("https://x.example.com/y") and out.index("Open shell") < out.index("uv run a"), out)
    check("8b a ! line first: the link on the next box, once", out2.count("Open shell") == 1 and out2.index("Open shell") > out2.index("! sala x") and out2.index("Open shell") < out2.index("uv run a"), out2)
    check("8b only a link: no Open shell at all", "Open shell" not in ui_render._cmd_blocks(["https://x.example.com/y"]))
    for what, i in (("a bare link first", 19), ("a ! line first", 20)):
        check(f"8b {what}, Your step block: one link, on the command", len(links(block(i))) == 1 and block(i).index("Open shell") < block(i).index("uv run a.py"), block(i))
        check(f"8b {what}, home row: one link, on the command", len(links(row(i))) == 1 and row(i).index("Open shell") < row(i).index("uv run a.py"), row(i)[:1200])

    # ---- 9. shell_url without sala-shell
    def mode_notes(owner_shell, v):
        cfg = {**C.CFG, "steps": {**WAS, "owner_shell": owner_shell, "shell_url": v}}
        return [n for n in C.notes(cfg) if "shell_url" in n]
    for osh in ("", "powershell"):
        got = mode_notes(osh, URL)
        check(f"9 owner_shell {osh!r} with a shell_url: exactly one note, saying it only applies with sala-shell", len(got) == 1 and 'owner_shell = "sala-shell"' in got[0] and "only applies" in got[0], got)
    check("9 sala-shell with a shell_url: no note", mode_notes("sala-shell", URL) == [], mode_notes("sala-shell", URL))
    check("9 no shell_url, any owner_shell: no note", mode_notes("powershell", "") == [] and mode_notes("", None) == [], (mode_notes("powershell", ""), mode_notes("", None)))
    check("9 an invalid shell_url with a wrong owner_shell: still one note", len(mode_notes("powershell", "javascript:x")) == 1, mode_notes("powershell", "javascript:x"))
finally:
    STEPS.clear(); STEPS.update(WAS)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.stdout.flush()
os._exit(1 if fails else 0)
