"""step_commands.py — the step of a your-step item as a numbered list with commands to copy, and the write guards that keep the commands in the step (a step says where a command runs, its shell commands default to PowerShell on a Windows machine with no ssh, they sit in a code block with a copy button
in the step rather than the description, and the steps are a numbered list, not bullets).

The step (metadata.step, states.py) is one line, or, when it has a numbered line (`1.` or `1)` at the start of a line) or a fenced block, a few lines kept as written. parse() reads it into the
parts the item page and the home row draw: plain lines, an ordered list whose items hold their commands, and a command block standing alone. A command is a backticked span with a space in it (the
rule home.copyables has always had; a lone word stays inline) or a fenced ``` block; each is drawn in a code block with a Copy button.

The step is a ONE-LINE SUMMARY of what he does, and what he runs
goes in the "<owner>:" lines of next, which his Your step block draws in full with their copy boxes (render.step_nexts_html). A step that carries a command (a backticked span that looks like a shell command,
a `! ` line, a fenced block) is refused, and the refusal says to put the command in a "<owner>:" line of next. The check on those next lines (where a command runs, the ssh form) is another build's
(the builder's, model_guards): command_problem below, the check the step used to get, is the one it reuses (`where="next line"`). It also still judges a step stored with a command before this rule,
on a write that leaves the step alone (`problem`); a write that sets the step is judged by step_carries_command instead.

The write guards (`problem`) judge an item a write leaves in state your-step with the owner as the mover, in this order, and give one line that names the field and the fix. One more guard reaches
every item that is his to move (he is its mover, or its state is your-step or your-call, stored or derived, or its needs hold his decision, "Description becomes Background, never steps"): its description holds no numbered line (`1.`, `2)`)
and no `! ` line outside a fenced block (judged on what the write adds); an agent's own items keep their ordinary multi-step descriptions.
  1. description  a shell command in the description (a fenced block with one in it, or a backticked span that looks like a shell command: a known command word or a path, then arguments): it goes in step
  4. step         the step points elsewhere ("in the description", "see below", "see description"): the step says what he does, in one line
  3. step         a step stored with a command before an earlier change, on a write that leaves it alone: a command that is bash for the host (sala, systemctl, python3, ./x, ~/x, $(…) …) without `ssh -t <host> '<command>'`
  2. step         …or a command and no word that says where it runs: PowerShell or Windows (his machine, the default); "a terminal on the host" is not a place
  0. step / next  a `! ` line (or a backticked `! cmd`) is refused first, in a step and in a "<owner>:" line of next, whatever else it says: the board takes no pane form, the command is "In PowerShell:" `ssh -t <host> '<command>'` (or, with [steps] owner_shell = "sala-shell", as typed in sala's Shell)
  2b. step        a step a write SETS that carries a command: it goes in a "<owner>:" line of next, with the place it runs; the step is a one-line summary that says so
Where he runs a command is [steps] owner_shell (shell_mode): "powershell" (the rules above), "sala-shell" (a command is bash as typed in sala's Shell, which runs on [steps] bash_host, or `ssh <host> '<command>'` for another
machine: no place is asked for, and a PowerShell or Windows-only command outside ssh is refused: windows_only), or "" (no place asked).
Pure functions of a text and an item: no server import, so the server, the renderer and the guard share one copy."""
from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass, field
from typing import Any

import config as _cfg
import draft as _draft
import model as _model

NUM_RX = re.compile(r"^[ \t]*(\d{1,3})[.)][ \t]+(\S.*)$")
FENCE_RX = re.compile(r"^[ \t]*(`{3,}|~{3,})[ \t]*([\w+.#-]*)[ \t]*$")      # group 2: the tag (```bash)
SHELL_TAGS = frozenset("sh bash shell powershell pwsh console".split())      # a fence in a description holds commands only when tagged so; an untagged one holds pasted output
SPAN_RX = re.compile(r"`([^`\n]+)`")


# ------------------------------------------------------------------------------------------------------------ reading a step
def lines_of(text: Any) -> list[str]:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")


def structured(text: Any) -> bool:
    """Does the step hold a numbered line or a fenced block (so it is kept as lines, not collapsed to one)?"""
    return any(NUM_RX.match(ln) or FENCE_RX.match(ln) for ln in lines_of(text))


@dataclass
class Item:
    """One numbered line: its text (command spans still in it) and the fenced blocks under it."""
    text: str
    fences: list[str] = field(default_factory=list)


@dataclass
class Part:
    """kind "text": one plain line (text); "ol": a numbered list (items, first number in start); "cmd": a fenced block standing alone (text)."""
    kind: str
    text: str = ""
    items: list[Item] = field(default_factory=list)
    start: int = 1


def _fence_body(lines: list[str], i: int) -> tuple[str, int]:
    """(the block's text, the index after its closing fence) for the fence opened on lines[i]; an unclosed fence runs to the end."""
    m = FENCE_RX.match(lines[i])
    ch, n = m.group(1)[0], len(m.group(1))
    body: list[str] = []
    j = i + 1
    while j < len(lines):
        s = lines[j].strip()
        if s and set(s) == {ch} and len(s) >= n:
            return textwrap.dedent("\n".join(body)).strip("\n"), j + 1
        body.append(lines[j].rstrip())
        j += 1
    return textwrap.dedent("\n".join(body)).strip("\n"), j


def parse(text: Any) -> list[Part]:
    """The step as parts. A numbered line opens an item (consecutive ones make one list); an indented line after an item goes on its text; a fenced block right after an item belongs to it, any
    other fenced block stands alone; a plain line that is not indented is a text part and ends the list. Blank lines are skipped."""
    lines = lines_of(text)
    parts: list[Part] = []
    cur: Item | None = None
    i = 0
    while i < len(lines):
        ln = lines[i]
        if FENCE_RX.match(ln):
            body, i = _fence_body(lines, i)
            if body.strip():
                if cur is not None:
                    cur.fences.append(body)
                else:
                    parts.append(Part("cmd", body))
            continue
        i += 1
        if not ln.strip():
            continue
        m = NUM_RX.match(ln)
        if m:
            cur = Item(m.group(2).strip())
            if parts and parts[-1].kind == "ol":
                parts[-1].items.append(cur)
            else:
                parts.append(Part("ol", items=[cur], start=int(m.group(1))))
        elif cur is not None and ln[:1] in (" ", "\t"):
            cur.text += " " + ln.strip()
        else:
            parts.append(Part("text", ln.strip()))
            cur = None
    return parts


_SEP_ONLY = re.compile(r"^[\s,;:.&+/-]*(?:\b(?:and|then|or)\b[\s,;:.&+/-]*)*$", re.I)


def split_spans(text: str) -> tuple[str, list[str]]:
    """(the line with each command span out of it, the commands). A span is a command when it has a space in it (a lone word stays inline). The line says "the command below" ("command 1 below" …) where
    a command was, except where the span ended the line after a colon (it is dropped: "In PowerShell:" then the block) and when nothing but commands was on the line (no text at all)."""
    spans = [m for m in SPAN_RX.finditer(text) if " " in m.group(1).strip()]
    if not spans:
        return text, []
    cmds = [m.group(1).strip() for m in spans]
    out: list[str] = []
    pos = 0
    for k, m in enumerate(spans):
        out.append(text[pos:m.start()])
        last = k == len(spans) - 1
        if last and text[m.end():].strip() == "" and re.search(r":\s*$", "".join(out)):
            pass                                              # "In PowerShell:" + the block: no placeholder after the colon
        else:
            out.append("the command below" if len(cmds) == 1 else f"command {k + 1} below")
        pos = m.end()
    out.append(text[pos:])
    line = "".join(out)
    if _SEP_ONLY.match(re.sub(r"(?:the command|command \d+) below", "", line)):
        return "", cmds
    return " ".join(line.split()), cmds


def commands_of(text: Any) -> list[str]:
    """Every command in the step, in order: the spans with a space in them, and the fenced blocks (each whole). A legacy whole-step `! cmd` is one command."""
    t = str(text or "").strip()
    if not structured(t):
        return [t] if t.startswith("!") else [m.group(1).strip() for m in SPAN_RX.finditer(t) if " " in m.group(1).strip()]
    out: list[str] = []
    for p in parse(t):
        if p.kind == "cmd":
            out.append(p.text)
        elif p.kind == "text":
            out += split_spans(p.text)[1]
        else:
            for it in p.items:
                out += split_spans(it.text)[1] + it.fences
    return out


def prose_of(text: Any) -> str:
    """The step's own words: fenced blocks and backticked spans taken out, so a command's words (a path with "windows" in it) say nothing about where it runs."""
    out: list[str] = []
    fence = ""
    for ln in lines_of(text):
        m = FENCE_RX.match(ln)
        if fence:
            if ln.strip() and set(ln.strip()) == {fence[0]} and len(ln.strip()) >= len(fence):
                fence = ""
            continue
        if m:
            fence = m.group(1)
            continue
        out.append(SPAN_RX.sub(" ", ln))
    return " ".join(" ".join(out).split())


# ------------------------------------------------------------------------------------------------------------ what looks like a shell command
# Known command words (a span whose first word is one of them, with arguments, is a shell command), the programs Linux boxes and the fleet's tools run. Tested in tests/step_scenario.py.
COMMAND_WORDS = frozenset("""
cd ls cat grep egrep sed awk chmod chown mkdir rmdir rm cp mv ln touch tail tee echo printf export unset source sudo su
ssh scp sftp rsync sh bash zsh fish git gh uv uvx pip pip3 python python3 py node npm npx pnpm yarn bun deno cargo rustup cmake
docker docker-compose podman kubectl helm terraform
sala claude stackshot gbrain tmux systemctl journalctl loginctl timedatectl hostnamectl resolvectl apt apt-get aptitude dpkg snap flatpak crontab
kill pkill killall ps htop df du umount nohup setsid timeout xargs uniq wc tr diff patch
curl wget tar unzip zip gzip gunzip jq yq nc ncat ping dig nslookup traceroute openssl gpg tailscale ip ifconfig ss netstat lsof
winget choco scoop wsl ipconfig netsh taskkill tasklist powershell pwsh cmd
""".split())
# Words that are also English (a button or a menu says "Make a copy", "Sort by date", "Go to settings", "Find and replace", "top 5", "Free trial"): a command only when a flag, a path or another
# argument-shaped token follows (make -j4, go build ./..., find . -name x, sort -u f.txt, top -b), never on words alone.
AMBIGUOUS = frozenset("go make find sort top free cut more less head watch mount reg sc screen".split())
# bash for a Linux box such as the host, which a PowerShell prompt does not run (a cross-platform tool such as git, gh, uv, curl or tailscale is not on this list: it runs in PowerShell too)
LINUX_ONLY = frozenset("""
sudo su sala tmux screen systemctl journalctl loginctl timedatectl hostnamectl resolvectl apt apt-get aptitude dpkg snap flatpak crontab
sh bash zsh fish chmod chown grep egrep sed awk export unset source nohup setsid pkill killall df free mount umount xargs python3 pip3 ln tee less
""".split())
# PowerShell aliases of a Unix name: bash only when an argument is Unix-shaped (a flag, ~ or an absolute path)
UNIX_ALIASES = frozenset("ls cat cd rm cp mv mkdir rmdir echo kill ps sleep head tail touch find sort".split())      # (a flag makes it bash: `ls -la`; a ~/ path does not: `cd ~/Documents` is PowerShell too)
_ENV_RX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*$")
_CMDLET_RX = re.compile(r"^[A-Z][a-z]+-[A-Z][A-Za-z]+$")
_BASH_SYNTAX = re.compile(r"\$\(|/dev/null|\s2>&1|<<-?\s*['\"]?\w|\s\\$|(?:^|\s)/(?:home|etc|var|usr|opt|tmp|root)/")
_PROMPT = re.compile(r"^(?:\$|#|PS>|PS [^>]*>|>)\s+")


def _words(line: str) -> list[str]:
    s = _PROMPT.sub("", line.strip(), count=1)
    toks = s.split()
    while toks and _ENV_RX.match(toks[0]):
        toks.pop(0)
    return toks


def is_pane_line(cmd: str) -> bool:
    """A `! cmd` line: typed into a Claude Code pane, which runs it as a shell command there."""
    return bool(re.match(r"^!\s*\S", cmd.strip()))


_ARG_RX = re.compile(r"^(?:--?[A-Za-z][\w-]*(?:=\S*)?|[^\s=]*[/\\][^\s]*|[\w.-]+=\S*|[\w-]+\.[A-Za-z0-9]{1,5}|[$~.]\S*)$")
_VERSION_RX = re.compile(r"^v?\d+(?:\.\d+)+$")                           # 5.5, 3.12, v4.0: a version or a size, not a file
_TITLE_PAIR_RX = re.compile(r"^[A-Z][a-z]+(?:/[A-Z][a-z]+)+$")           # Date/Time: two capitalised words, not a path
_FLAG_RX = re.compile(r"^(?:--?[A-Za-z][\w-]*(?:=\S*)?|/[A-Za-z?][\w-]*|\$\S*|~/\S*|\./\S*)$")      # a flag: -x, --long, /x (the whole token), $var, a ~/ or ./ path


def argshaped(toks: list[str]) -> bool:
    """Does an argument follow that only a command line has: a flag (-x, --long), a path (with / or a backslash), key=value, a file with an extension, $var, ~ or . ? A plain word or a number does not."""
    return any(_ARG_RX.match(t) and not _VERSION_RX.match(t) and not _TITLE_PAIR_RX.match(t) for t in toks)


def flagshaped(toks: list[str]) -> bool:
    """Does a flag-shaped token follow: -x, --long, /x (the whole token), $var, a ~/ or ./ path? A word, a number, a file name or a path such as Date/Time does not."""
    return any(_FLAG_RX.match(t) for t in toks)


def _title_name(w: str) -> bool:
    """A first word that starts with an uppercase letter and is no cmdlet (Verb-Noun), path or drive letter: a label or a product name (`Export data`, `Docker Desktop`, `Su Kim`), not a command."""
    return w[:1].isupper() and not (_CMDLET_RX.match(w) or w.startswith(("$", "&")) or re.match(r"^[A-Za-z]:\\", w))


def _first_is_command(toks: list[str], fenced: bool) -> bool:
    if not toks:
        return False
    w, multi = toks[0], len(toks) > 1
    if _title_name(w):
        return flagshaped(toks[1:])
    if w.lower() in AMBIGUOUS:
        return argshaped(toks[1:])
    path = w.startswith(("./", "~/", "/", "../", ".\\"))
    if _CMDLET_RX.match(w) or w.startswith(("$", "&")) or re.match(r"^[A-Za-z]:\\", w):
        return multi or fenced
    if w.lower() in COMMAND_WORDS:
        return multi or fenced
    return path and (multi or fenced)


def looks_like_command(span: str, fenced: bool = False) -> bool:
    """Does this backticked span (or a line of a fenced block, fenced=True: a lone word counts there) look like a shell command? A `! cmd` line does; so does a known command word, a cmdlet or a path
    followed by arguments. A lone word or a bare path in a sentence ("`git`", "`~/stackshot/render.py`") is a name, not a command."""
    s = span.strip()
    if not s:
        return False
    if is_pane_line(s):
        return True
    return _first_is_command(_words(s), fenced)


def _inside_lines(body: str) -> set[int]:
    """The indexes of the lines of a fenced block that start inside an open quote or a heredoc a command line began (`ssh host '` then the quoted lines): they are another program's text, not commands."""
    inside: set[int] = set()
    q, hd = "", ""
    for i, ln in enumerate(str(body or "").split("\n")):
        if q or hd:
            inside.add(i)
        if hd:
            if ln.strip() == hd:
                hd = ""
            continue
        if not q and ln.strip().startswith("#"):
            continue
        j, n = 0, len(ln)
        while j < n:
            c = ln[j]
            if q:
                if c == "\\" and q == '"':
                    j += 1
                elif c == q:
                    q = ""
            elif c == "\\":
                j += 1
            elif c in ("'", '"'):
                q = c
            j += 1
        if not q:
            m = re.search(r"<<-?\s*(['\"]?)(\w+)\1", ln)
            if m:
                hd = m.group(2)
    return inside


def fence_commands(body: str, bodies: bool = True) -> list[str]:
    """The command lines of a fenced block: the lines that start one (not blank, not a comment, not a continuation of the line above or an indented line). Once a bare `claude` line has
    started the REPL, the lines after it are typed into it, not run by the shell: they are skipped. `bodies=False` also leaves out the lines inside a quote or heredoc a command opened
    (`ssh host '`, the lines, `'`): what sala-shell mode judges as bash."""
    out: list[str] = []
    prev = ""
    skip = set() if bodies else _inside_lines(body)
    for i, ln in enumerate(str(body or "").split("\n")):
        s = ln.strip()
        cont = prev.endswith(("\\", "`", "|", "&&", ",")) or ln[:1] in (" ", "\t")
        prev = s
        if not s or s.startswith(("#", "//")) or cont or i in skip:
            continue
        out.append(s)
        if s == "claude":
            break
    return out


def bash_for_host(cmd: str) -> bool:
    """Is this command bash meant for the host (so it needs `ssh -t <host> '<command>'` from his PowerShell)? Not a `! ` line, not an ssh command, not a cmdlet; a Linux-only program, a
    absolute or ./ path, bash syntax, or a Unix alias with a flag. A ~/ path alone is not enough: `cd ~/Documents`, `cat ~/notes.txt` and `git -C ~/repo pull` are PowerShell too."""
    s = cmd.strip()
    if is_pane_line(s):
        return False
    toks = _words(s)
    if not toks:
        return False
    w = toks[0]
    if w.lower() == "ssh" or _CMDLET_RX.match(w) or w.startswith(("$", "&")) or re.match(r"^[A-Za-z]:\\", w):
        return False
    if _title_name(w) and not flagshaped(toks[1:]):
        return False
    if w.lower() in AMBIGUOUS and not argshaped(toks[1:]):
        return False
    if w.startswith(("./", "/", "../")) or w.lower() in LINUX_ONLY or _BASH_SYNTAX.search(s):
        return True
    return w.lower() in UNIX_ALIASES and any(re.match(r"^-[A-Za-z]+$", t) for t in toks[1:])


# ------------------------------------------------------------------------------------------------------------ does a text ask him to run something
# A text asks him to run a command when an imperative run cue comes before the command (run, type, typing, execute, enter; paste only when it names a terminal or shell: "paste this reply" is a
# paste of text; with [keywords.step_commands] run_commands, or after_command right after the command's closing backtick) or when a line opens with a place phrase ("In PowerShell:", "In a terminal …"). A text that only mentions a
# command ("decide whether `git push` …", "the fix is `systemctl …`") does not, and neither does one where someone else runs it ("say go and I will run …", "tell the session to run …", "the nightly run will do …").
_CUE_RX = re.compile(r"(?<![A-Za-z])(?:run|type|typing|execute|enter)(?![A-Za-z])", re.I)
_PASTE_RX = re.compile(r"(?<![A-Za-z])(?:paste|pastes|pasting)(?![A-Za-z])", re.I)
# The words of another language are the instance's own ([keywords.step_commands] in stackshot.toml, config.KEYWORDS): they add to the English ones below, and none is the English behavior.
def _term_rx() -> "re.Pattern[str]":
    return _cfg.kw_rx("sc.term", lambda a: r"(?<![A-Za-z])(?:terminal|power\s?shell|pwsh|shell|wsl|console|command\s+prompt)(?![A-Za-z])" + _cfg.kw_pipe(a), (("step_commands", "shell_names"),), re.I)


def _run_commands_rx() -> "re.Pattern[str]":
    return _cfg.kw_rx("sc.runcmd", lambda a: a or _cfg._NEVER, (("step_commands", "run_commands"),), re.I)


def _after_command_rx() -> "re.Pattern[str]":
    return re.compile(r"[ \t]*(?:" + (_cfg.kw_alt("step_commands", "after_command", r"[ \t]*") or _cfg._NEVER) + ")", re.I)


def _subject_rx() -> "re.Pattern[str]":
    return _cfg.kw_rx("sc.subj", lambda a: r"(?:" + (a or _cfg._NEVER) + r")\s*$", (("step_commands", "subject_markers"),), re.I)


def _place_head_rx(sala: bool) -> "re.Pattern[str]":
    pre = r"^\s*(?:in|on|from|inside|using)\s+(?:a\s+|an\s+|the\s+|your\s+|his\s+|my\s+)?" + (r"(?:sala(?:['\u2019]s)?\s+)?" if sala else "") + r"(?:windows\s+)?(?:power\s?shell|pwsh|wsl|terminal|shell|command\s+prompt)(?![A-Za-z])"
    return _cfg.kw_rx("sc.place" + ("s" if sala else ""), lambda a: pre + (r"|^\s*(?:" + a + ")" if a else ""), (("step_commands", "shell_names"),), re.I)


# …and the one sala-shell mode reads: "In sala's Shell:" is a place phrase there; with the default and the PowerShell setting that text is no place, as it never was.
_LEAD_RX = re.compile(r"^\s*(?:[-*+•]|\d{1,3}[.)])?\s*")
_NOT_HIS = frozenset("i we will to a an the next nightly".split())      # "I will run", "to run", "the run", "next run": someone else runs it, or it is a noun
_SENTENCE_STOP = re.compile(r"[.!?](?:\s|$)")
_TRAIL_STOP = ".!?;,"
_VALUE_STOP = frozenset("and then or so in on at to for when if but with while after before once until".split())      # a word after a flag that is not its value


def blank_code(text: Any) -> str:
    """The text with every fenced block (fence lines included) and every backticked span replaced by spaces, same length and same line breaks: what is left is the text's own words."""
    out: list[str] = []
    fence = ""
    for ln in lines_of(text):
        if fence:
            if ln.strip() and set(ln.strip()) == {fence[0]} and len(ln.strip()) >= len(fence):
                fence = ""
            out.append(" " * len(ln))
            continue
        m = FENCE_RX.match(ln)
        if m:
            fence = m.group(1)
            out.append(" " * len(ln))
            continue
        out.append(SPAN_RX.sub(lambda x: " " * len(x.group(0)), ln))
    return "\n".join(out)


def _place_rx() -> "re.Pattern[str]":
    return _place_head_rx(sala_shell())


def _lead_blank(line: str) -> str:
    """The line with its bold marks and list marker replaced by spaces (same length), so a place phrase after `1. `, `- ` or `**` is found."""
    s = line.replace("**", "  ")
    return " " * _LEAD_RX.match(s).end() + s[_LEAD_RX.match(s).end():]


def _cues(blank: str, roster: "set[str] | None" = None) -> list[tuple[int, int]]:
    """[(start, end)] of the imperative run cues in a text whose code is blanked: run, type, typing, execute, enter, and paste beside a terminal or shell, minus those where someone else runs it or the
    word is a noun: after I, we, will, 'll, to, an article, next, nightly or a session of the roster, or before "of"."""
    spots = [m.span() for m in _CUE_RX.finditer(blank)]
    if _term_rx().search(blank):
        spots += [m.span() for m in _PASTE_RX.finditer(blank)]
    out: list[tuple[int, int]] = []
    for a, b in sorted(spots):
        prev = re.search(r"([A-Za-z0-9_'’-]+)\W*$", blank[:a])
        w = prev.group(1).lower().replace("’", "'") if prev else ""
        if w in _NOT_HIS or w.endswith("'ll") or (roster and w in roster) or re.match(r"\s+of(?![A-Za-z])", blank[b:], re.I):
            continue
        out.append((a, b))
    return out


def _after_span(text: str) -> bool:
    """Does a configured run word ([keywords.step_commands] after_command: the verb that follows its object in some languages) follow a command's closing backtick directly, with no subject
    marker before the command ([keywords.step_commands] subject_markers: a session named as the subject runs it)? False with no such words."""
    for m in SPAN_RX.finditer(text):
        if _after_command_rx().match(text[m.end():]) and not _subject_rx().search(text[:m.start()]):
            return True
    return False


def run_cue(text: Any, roster: "set[str] | None" = None) -> int | None:
    """Where in the text the ask to run something begins (None: it asks nothing of the kind): the start of the first line that opens with a place phrase (after a list marker or bold), 0 for a configured cue
    (run_commands, after_command: in some languages the verb follows its object), else the position of the first imperative run cue in the text's own words (code spans and fences do not count; `roster`: session names, casefolded, who may be
    named before a cue)."""
    t = "\n".join(lines_of(text))
    blank = blank_code(t)
    found: list[int] = []
    off = 0
    for ln in blank.split("\n"):
        if _place_rx().match(_lead_blank(ln)):
            found.append(off)
            break
        off += len(ln) + 1
    if _run_commands_rx().search(blank) or _after_span(t):
        found.append(0)
    cues = _cues(blank, roster)
    if cues:
        found.append(cues[0][0])
    return min(found) if found else None


def _trim_command(toks: list[str]) -> tuple[list[str], int]:
    """(the tokens of the command, the index of its first argument-shaped token or -1): from its first word to the last flag, path or quoted argument (and a flag's value), cut at a sentence stop."""
    last, first, q = 0, -1, ""
    for i, t in enumerate(toks):
        core = t
        stop = bool(core) and core[-1] in _TRAIL_STOP and not q
        if stop:
            core = core.rstrip(_TRAIL_STOP)
        anchor = False
        if i > 0:
            if q:
                anchor = True
                if core.endswith(q):
                    q = ""
            elif core[:1] in ("'", '"'):
                anchor = True
                if not (len(core) > 1 and core.endswith(core[0])):
                    q = core[0]
            elif core and _ARG_RX.match(core) and not _VERSION_RX.match(core) and not _TITLE_PAIR_RX.match(core):
                anchor = True
            elif core and toks[i - 1].startswith("-") and last == i - 1 and core.lower() not in _VALUE_STOP and re.match(r"^[\w.@:/-]+$", core):
                anchor = True
        if anchor:
            last = i
            if first < 0:
                first = i
        if stop:
            toks = toks[:i + 1]
            toks[i] = core
            break
    return toks[:last + 1], first


def _bare_candidates(text: Any, roster: "set[str] | None" = None) -> list[list[str]]:
    """The token lists where a bare command may begin: after a run cue, after a place phrase, and after a colon that ends the clause of either (within eight words, no sentence stop between). A cue
    or place colon that ends its line hands over to the next non-blank line, when that is plain text (a fenced block or a backticked command there is already in code)."""
    orig = lines_of(text)
    blank = blank_code(text).split("\n")
    out: list[list[str]] = []
    for idx, ln in enumerate(blank):
        lead = _lead_blank(ln)
        anchors = [b for _, b in _cues(ln, roster)]
        place = _place_rx().match(lead)
        if place:
            anchors.append(place.end())
        if not anchors:
            continue
        pts = list(anchors)
        for i in range(min(anchors), len(lead)):
            if lead[i] != ":":
                continue
            a = max(p for p in anchors if p <= i) if any(p <= i for p in anchors) else None
            seg = lead[a:i] if a is not None else ""
            if a is not None and len(seg.split()) <= 8 and not _SENTENCE_STOP.search(seg):
                pts.append(i + 1)
        for p in pts:
            toks = lead[p:].split()
            while toks and set(toks[0]) <= set(":*,"):
                toks.pop(0)
            if not toks:
                j = idx + 1
                while j < len(blank) and not orig[j].strip():
                    j += 1
                if j < len(blank):
                    toks = _lead_blank(blank[j]).split()
            if toks and toks[0] == "!":
                toks = toks[1:]
            if toks:
                out.append(toks)
    return out


def bare_command(text: Any, roster: "set[str] | None" = None) -> str:
    """A command written outside backticks and outside a fence after a run cue or a place phrase ("typing the token when asked: ssh -t <host> '…'"), "" when none, trimmed to the command itself: it
    starts with a known command word (COMMAND_WORDS), a cmdlet or a path (a `! ` before it is the pane form) and has a flag, path or quoted argument among its first four words. Prose after a cue ("run the
    cleanup when you're back", "Run this: git can't push") is not one, and neither is a bare command with none of those. The board draws a command only when it is in backticks or a fence, so a bare one has
    no Copy button."""
    for toks in _bare_candidates(text, roster):
        if len(toks) < 2:
            continue
        w = toks[0].strip("\"'")
        if not (w.lower() in COMMAND_WORDS or _CMDLET_RX.match(w) or w.startswith(("./", "~/", "/"))):
            continue
        cmd, first = _trim_command([w, *toks[1:]])
        if 1 <= first <= 4:
            return " ".join(cmd)
    return ""


# ------------------------------------------------------------------------------------------------------------ the guards
def _win_rx() -> "re.Pattern[str]":
    return _cfg.kw_rx("sc.win", lambda a, b: r"(?<![A-Za-z])(?:power\s?shell|pwsh|wsl|windows|win\s?(?:10|11))(?![A-Za-z])" + _cfg.kw_pipe(a) + _cfg.kw_pipe(b),
                      (("step_commands", "shell_names"), ("step_commands", "windows_words")), re.I)


# A step that sends him to another place for what he does. "below" alone is not here: his own commands sit below the step's text, and "the command below" is how the page says so.
# [keywords.step_commands] pointer_patterns adds the instance's own language (regular expressions).
def _points_rx() -> "re.Pattern[str]":
    return _cfg.kw_rx("sc.points", lambda a: (
        r"(?<![A-Za-z])(?:see|refer\s+to|as\s+described\s+in)\s+(?:the\s+|this\s+)?(?:item\s+)?(?:description|below|above)(?![A-Za-z])"
        r"|(?<![A-Za-z])(?:in|from)\s+the\s+(?:item\s+)?description(?![A-Za-z])"
        r"|(?<![A-Za-z])(?:described|listed|written|noted|given|detailed)\s+(?:in\s+the\s+description|below|above)(?![A-Za-z])"
        r"|(?<![A-Za-z])(?:steps|commands)\s+(?:are\s+)?(?:below|above)(?![A-Za-z])") + _cfg.kw_pipe(a), (("step_commands", "pointer_patterns"),), re.I)
def shell_mode() -> str:
    """Where the owner runs the commands of a board step ([steps] owner_shell): "powershell" (PowerShell on a Windows machine, the Linux host over ssh), "sala-shell" (sala's Shell, a terminal in the
    sala web UI that runs bash on the Linux host; another machine over ssh), or "" (the default: no place is asked for)."""
    return _cfg.owner_shell_mode()


def shell_rule() -> bool:
    """Does this instance's owner run board steps in PowerShell on a Windows machine ([steps] owner_shell = "powershell")? Then a step's command says where it runs and a command that is bash for
    the Linux host is written as `ssh -t <host> '<command>'`. Off (the default, and with "sala-shell"): no place is asked for."""
    return shell_mode() == "powershell"


def sala_shell() -> bool:
    """Does the owner run board steps in sala's Shell ([steps] owner_shell = "sala-shell")? Then a command is bash as typed there (it runs on [steps] bash_host), or `ssh <host> '<command>'` for another
    machine; no line saying where it runs is asked for, and a PowerShell or Windows-only command that is not inside ssh is refused."""
    return shell_mode() == "sala-shell"


def shell_name() -> str:
    """The instance's name for its sala Shell session ([steps] shell_name); "" = none named (the text then says "sala's Shell" alone)."""
    return str(_cfg.get("steps", "shell_name", default="") or "").strip()


def shell_place() -> str:
    """How the text names the place the owner types a command in sala-shell mode: "sala's Shell", with the session's name when [steps] shell_name gives one."""
    n = shell_name()
    return "sala's Shell" + (f" (the session `{n}`)" if n else "")


def bash_host() -> str:
    """The Linux host a bash command of a step is run on ([steps] bash_host): over ssh from the owner's PowerShell, or where sala's Shell runs; "" when none is named."""
    return str(_cfg.get("steps", "bash_host", default="") or "").strip()


def bash_fix() -> str:
    return f"ssh -t {bash_host() or '<host>'} '<command>'"


def other_host_form() -> str:
    """A command for another machine in sala-shell mode, as typed in the Shell."""
    return "ssh <host> '<command>'"


# What a sala Shell (bash) cannot run on its own: a PowerShell cmdlet, a call operator, a drive path, a Windows-only program. Inside `ssh <host> '…'` the command is the other machine's, so it passes.
WINDOWS_ONLY = frozenset("winget choco scoop wsl ipconfig netsh taskkill tasklist powershell pwsh cmd".split())


def windows_only(cmd: str) -> bool:
    """Is this command PowerShell or Windows-only, so bash does not run it (a cmdlet, `&`, a drive path, a program of WINDOWS_ONLY)? An ssh command is the other machine's and is not."""
    s = cmd.strip()
    if is_pane_line(s):
        return False
    toks = _words(s)
    if not toks:
        return False
    w = toks[0]
    if w.lower() == "ssh":
        return False
    return bool(_CMDLET_RX.match(w) or w.startswith(("&", ".\\")) or re.match(r"^[A-Za-z]:\\", w) or w.lower() in WINDOWS_ONLY)


_PANE_START_RX = re.compile(r"^!\s+\S")
# A `!` and a command word in the middle of a line: after a colon ("In PowerShell: ! sala x", "In the pane type: ! sala x") or after a run cue ("type ! sala x"). A `!` stuck to a
# word ("done!", "wow!") or to the next one ("!important") is prose and passes. A fenced `! grep` line and a line starting `! Note:` are false positives, accepted.
def _pane_inline_rx() -> "re.Pattern[str]":
    return _cfg.kw_rx("sc.pane", lambda a: r"(?:(?<![A-Za-z])(?:type|run|enter|execute|paste" + _cfg.kw_pipe(a) + r")\s+|:\s*)(!\s+[A-Za-z./~$_][^\s`]*(?:\s+[^\s`]+)*)", (("step_commands", "pane_cues"),), re.I)


def pane_commands(text: Any) -> list[str]:
    """The pane-form commands a text holds: a line that starts `! ` + a command (after a list marker), a backticked span that does, or a `! ` + command after a colon or a run cue in a line. A `!` that no command follows ("done!", a
    quoted "`! `") is none. The board takes no pane form: a command for the owner on it is `ssh <host> '<command>'` from the owner's Windows machine."""
    out: list[str] = []
    for ln in lines_of(text):
        s = _LEAD_RX.sub("", ln.strip()).replace("**", "").strip()
        if _PANE_START_RX.match(s):
            out.append(s)
        else:
            m = _pane_inline_rx().search(s)
            if m:
                out.append(m.group(1).strip())
        out += [m.group(1).strip() for m in SPAN_RX.finditer(ln) if _PANE_START_RX.match(m.group(1).strip())]
    return out


def pane_problem(text: Any, where: str = "step") -> str:
    """Why a text is refused for a pane-form command ("" = it holds none). One line that names the field and the fix: the ssh form from his PowerShell."""
    cmds = pane_commands(text)
    if not cmds:
        return ""
    if sala_shell():
        return (f"{where}: a `! ` line (`{_clip(cmds[0])}`) is a command typed into a session's pane, and the board takes none; a command for {_model.owner_display()} is written in backticks "
                f"(or a fenced block) as typed in {shell_place()} (`{other_host_form()}` for another machine), never as a `! ` line")
    if not shell_rule():
        return (f"{where}: a `! ` line (`{_clip(cmds[0])}`) is a command typed into a session's pane, and the board takes none; a command for {_model.owner_display()} is written in backticks "
                "(or a fenced block), never as a `! ` line")
    return (f"{where}: a `! ` line (`{_clip(cmds[0])}`) is a command typed into a session's pane, and the board takes none; a command for {_model.owner_display()} is written \"In PowerShell:\" "
            f"`{bash_fix()}` (the owner's Windows machine, the default; for another host `ssh <host> '<command>'`), never as a `! ` line")


def points_elsewhere(step: Any) -> str:
    """The words of the step that send him to another place ("" when none): found in the step's own words, never inside a command."""
    m = _points_rx().search(prose_of(step))
    return m.group(0) if m else ""


def description_commands(description: Any) -> list[str]:
    """The shell commands a description holds: the command lines of a fenced block tagged sh, bash, shell, powershell, pwsh or console (an untagged fence holds pasted output, and is not
    read), and a backticked span (outside a fence) that looks like a shell command."""
    out: list[str] = []
    fence, shell, body = "", False, []
    for ln in lines_of(description):
        m = FENCE_RX.match(ln)
        if fence:
            if ln.strip() and set(ln.strip()) == {fence[0]} and len(ln.strip()) >= len(fence):
                fence = ""
                if shell:
                    out += [c for c in fence_commands("\n".join(body)) if looks_like_command(c, fenced=True)]
            else:
                body.append(ln)
            continue
        if m:
            fence, shell, body = m.group(1), m.group(2).lower() in SHELL_TAGS, []
            continue
        out += [s.group(1).strip() for s in SPAN_RX.finditer(ln) if looks_like_command(s.group(1))]
    if fence and shell:
        out += [c for c in fence_commands("\n".join(body)) if looks_like_command(c, fenced=True)]
    return out


def added_commands(description: Any, prior: Any) -> list[str]:
    """The commands the description holds that the prior description did not (compared as written, one for one): a write that fixes a typo beside an old command adds none."""
    old = [" ".join(c.split()) for c in description_commands(prior)]
    out: list[str] = []
    for c in description_commands(description):
        k = " ".join(c.split())
        if k in old:
            old.remove(k)
        else:
            out.append(c)
    return out


def _clip(s: str, n: int = 60) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def step_commands(step: Any, bodies: bool = True) -> list[str]:
    """The commands of a step that look like shell commands, with every line of a fenced block (a fence is a command block whatever it holds): what the location and bash guards judge."""
    t = str(step or "").strip()
    out: list[str] = []
    if not structured(t):
        return [t] if t.startswith("!") and is_pane_line(t) else [c for c in commands_of(t) if looks_like_command(c)]
    for p in parse(t):
        blocks: list[str] = []
        spans: list[str] = []
        if p.kind == "cmd":
            blocks.append(p.text)
        elif p.kind == "text":
            spans += split_spans(p.text)[1]
        else:
            for it in p.items:
                spans += split_spans(it.text)[1]
                blocks += it.fences
        out += [c for c in spans if looks_like_command(c)]
        for b in blocks:
            out += fence_commands(b, bodies)
    return out


def step_carries_command(step: Any) -> str:
    """Why a step is refused for holding a command ("" = it holds none). The step is a one-line summary of what he does; every command he runs goes in a line of next that opens with his
    name, which his Your step block shows in full with a Copy button. One line that names the field, the command and the fix. A backticked label (a button, a menu) is not a command: bold or quotes."""
    pane = pane_problem(step, "step")
    if pane:
        return pane
    cmds = step_commands(step) or ([bare_command(step)] if bare_command(step) else [])      # a command in backticks or a fence, or one written bare after a run cue or a place phrase
    if not cmds:
        return ""
    return (f"step: it carries a command (`{_clip(cmds[0])}`); the step is a one-line summary of what {_model.owner_display()} does and holds no command: put the command, with the place it runs, in a "
            f"\"{_model.owner_display()}:\" line of next (in backticks or a ``` block; his Your step block shows that line in full, with a Copy button) and let the step say what he does; "
            "a button or menu label is not a command: use bold or quotes, not backticks")


def command_problem(step: Any, where: str = "step", roster: "set[str] | None" = None) -> str:
    """Why the step's commands are refused ("" = fine): bash for the host, or no word that says where they run. One line. `where` is the field the text names in the refusal: "step", or
    "next line" for a next line that starts with the owner's name (model_guards): the same judgement, the same text. `roster`: the session names (casefolded) a run cue may follow without being his."""
    pane = pane_problem(step, where)
    if pane:
        return pane
    bare = bare_command(step, roster)
    if bare:
        return f"{where}: the command `{_clip(bare)}` is not in backticks; put the command in backticks (or a fenced block) so the board shows a copy box"
    cmds = step_commands(step)
    if not cmds:
        return ""
    host = bash_host() or "the Linux host"
    if sala_shell():
        for c in step_commands(step, bodies=False):      # the lines inside a quote or heredoc an ssh line opened are the other machine's
            if windows_only(c):
                return (f"{where}: `{_clip(c)}` is PowerShell or Windows, and {_model.owner_display()}'s steps run in {shell_place()}, which is bash on {host}; write it as a bash command, "
                        f"or for another machine as `{other_host_form()}` (the command in quotes is that machine's); a button or menu label is not a command: use bold or quotes, not backticks")
        return ""
    if not shell_rule():
        return ""
    for c in cmds:
        if bash_for_host(c):
            return (f"{where}: `{_clip(c)}` is bash for {host}, and {_model.owner_display()}'s steps run in PowerShell on the owner's Windows machine; write it \"In PowerShell:\" `{bash_fix()}` (or, if this is a Windows path, say so); a button or menu label is not a command: use bold or quotes, not backticks")
    prose = prose_of(step)
    shell = [c for c in cmds if not is_pane_line(c)]
    if shell and not _win_rx().search(prose):
        start = "start with \"In PowerShell:\"" if where == "step" else f"write `{_model.owner_display()}: In PowerShell: …`"
        return (f"{where}: it has a command but does not say where it runs; {start} (the owner's Windows machine, the default for every shell command of the owner's; "
                f"for {host} write the command as `{bash_fix()}`), a terminal on {host} is not a place; a button or menu label is not a command: use bold or quotes, not backticks")
    return ""


OWNER_STATES = ("your-step", "your-call")      # the states that are his move: the item page draws his step or his ask for them
_LEAD = r"[ \t]*(?:[-*+\u2022][ \t]+)*"                  # an indent and any bullet markers a line may open with
_STEP_LINE_RX = re.compile(rf"^{_LEAD}\d{{1,3}}[.)][ \t]+(\S.*)$")      # `1. x`, `2) x`, `- 3. x`
_PANE_LINE_RX = re.compile(rf"^{_LEAD}!(?:[ \t]+\S.*)$")                # `! cmd`, `- ! cmd`


def owner_facing(item: dict[str, Any]) -> bool:
    """Is the open item his to move: the owner is its stored mover, or its state (stored, else derived from its fields) is one that is his move (your-step, your-call), or its needs hold his
    decision even with no state or mover stored? The item page shows such an item's step or ask first, and its description is the Background, never steps."""
    if item.get("status") == "completed":
        return False
    import states as _states      # states imports this module, so it is read when called
    m = item.get("metadata") or {}
    s, _derived = _states.of(item)
    return s in OWNER_STATES or _model.is_owner(_model.norm_who(m.get("mover"))) or "decision" in _states.kinds_of(m)


def _outside_fences(description: Any) -> list[str]:
    """The lines of a description that are not inside a fenced block (a fence holds pasted output or commands, judged elsewhere) and not a fence line."""
    out: list[str] = []
    fence = ""
    for ln in lines_of(description):
        if fence:
            if ln.strip() and set(ln.strip()) == {fence[0]} and len(ln.strip()) >= len(fence):
                fence = ""
            continue
        m = FENCE_RX.match(ln)
        if m:
            fence = m.group(1)
            continue
        out.append(ln)
    return out


def _unmatched(lines: list[str], rx: "re.Pattern[str]", prior: list[str] | None) -> list[str]:
    """The lines matching `rx` (their text after the marker, spaces collapsed) that `prior` did not hold, one for one; prior None = all of them."""
    mine = [" ".join(m.group(1).split()) if m.groups() else " ".join(ln.split()) for ln in lines if (m := rx.match(ln))]
    if prior is None:
        return mine
    old = [" ".join(m.group(1).split()) if m.groups() else " ".join(ln.split()) for ln in prior if (m := rx.match(ln))]
    out: list[str] = []
    for t in mine:
        if t in old:
            old.remove(t)
        else:
            out.append(t)
    return out


def description_steps(description: Any, prior: Any = None) -> tuple[list[str], list[str]]:
    """(the numbered lines, the `! ` lines) a description holds outside a fenced block; with `prior` (the description a write replaces) only those the prior did not hold (compared as written
    after the marker, one for one), so a typo fixed beside an old line adds none. A numbered line is `1.` or `2)` at a line's start, after any bullet marker."""
    cur = _outside_fences(description)
    old = None if prior is None else _outside_fences(prior)
    return _unmatched(cur, _STEP_LINE_RX, old), _unmatched(cur, _PANE_LINE_RX, old)


def problem(item: dict[str, Any], prior_description: Any = None, step_set: bool = False) -> str:
    """Why the item, as a write leaves it, is refused ("" = fine). Two judgements, one line each that names the field and the fix:
    - an item that is his to move (owner_facing: he is its mover, its state is your-step or your-call, stored or derived, or its needs hold his decision): its description is the item's background and holds no steps, so a numbered line (`1.`, `2)`)
      or a `! ` line in it is refused, pointing at step. Every other item keeps an agent's ordinary multi-step description (the narrowest form of "never steps");
    - an item in your-step with him as the mover: also a shell command in the description, a step that points elsewhere, or a step whose commands are bash for the host or do not say where they run.
    `prior_description` (a write that sets the description passes the one it replaces): only what the write adds or changes is judged, so a typo fixed beside an old command passes; None judges the
    whole description as stored (a write that leaves it alone, the report). `step_set` (the write sets the step): the step it sets carries no command, whatever the place it names; a step stored
    before that rule keeps the old judgement (a command needs a place, and bash for the host the ssh form) on the writes that leave it alone, until it is rewritten as a summary."""
    if not owner_facing(item):
        return ""
    numbered, bangs = description_steps(item.get("description"), prior_description)
    owner = _draft.owner_steps(item)
    cmds = []
    if owner:
        cmds = description_commands(item.get("description")) if prior_description is None else added_commands(item.get("description"), prior_description)
    if cmds:
        return (f"description: it holds a shell command (`{_clip(cmds[0])}`); a command {_model.owner_display()} runs goes in a \"{_model.owner_display()}:\" line of next, in backticks or a fenced block "
                "(his Your step block draws it there with a Copy button), never in the description; if it is not a command he runs, drop the backticks or the fence")
    if numbered:
        return (f"description: it holds numbered steps (\"{_clip(numbered[0], 40)}\"); the description is the item's Background and never holds steps: what {_model.owner_display()} does goes in \"{_model.owner_display()}:\" lines of next (his page draws them first, in Your step, under the state line) and step= is a one-line summary of them; "
                "if these are not steps for him, write them as `- ` bullets without numbers")
    if bangs:
        return (f"description: it holds a `! ` line (\"{_clip(bangs[0], 40)}\"), a command typed into a session's pane, and the board takes none; a command for {_model.owner_display()} goes in a \"{_model.owner_display()}:\" line of next" + (f", written \"In PowerShell:\" `{bash_fix()}`" if shell_rule() else f", written as typed in {shell_place()} (`{other_host_form()}` for another machine)" if sala_shell() else "") + ", "
                "never in the description")
    if not owner:
        return ""
    step = (item.get("metadata") or {}).get("step")
    hit = points_elsewhere(step)
    if hit:
        return (f"step: it points elsewhere (\"{hit}\"); the step is a one-line summary of what {_model.owner_display()} does and may name his Next line, but never the description or \"below\": "
                f"say what he does in the step, and put what he runs in a \"{_model.owner_display()}:\" line of next")
    return step_carries_command(step) if step_set else command_problem(step)
