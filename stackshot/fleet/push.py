"""push.py — deliver one notice line into a live Claude Code session's inbox.

  push.py [--from <sender>] <session> <text>
                                  deliver now, or queue when the session is not live: exit 0 delivered · 1 queued
                                  The drop opens with a `from: <sender>` line: --from, else $PUSH_FROM, else the
                                  calling program's name (its parent process), so a notice never reads as the owner's own prompt;
                                  with [anchor_hub] require_sender = true a drop without one is refused (exit 2)
  push.py --flush <session>       deliver everything queued for that session: exit 0 done (or nothing queued) · 3 not live · 4 failed · 5 paused or held
  push.py --list                  live sessions the CLI's registry can resolve (name → socket)

Targets. A pane on another machine, or on a machine whose puller is checking in (this box included): the line goes into
the server's inbox (inbox.py) and that machine fetches it (puller.py, or the session's drain hook on a machine with no
puller); the server box reaches into no other machine. A pane on
this box with no puller checking in, by name or transcript uuid: the CLI's own registry ~/.claude/sessions/<pid>.json maps
it to messagingSocketPath, live when the pid runs; one JSON line {"type":"user","message":{"role":"user","content":…}} on
the socket (the format the CLI's uds-messaging debug log shows). A cloud or Cowork session (cse_…): `claude --cloud <id> -p
<text>` queues it into the session as a user turn. Not delivered → queued in <state>/anchor-hub/queue[-msg]/<session>.jsonl;
anchor-hub flushes queues when a session comes back.

Sources: ANCHOR_PUSH_SOURCE=hub (anchor-hub's notices, the default) or msg (the message tool and the prompts it carries), each
with its own queue dir and pause flag. While paused-<source>.json exists a delivery is queued and --flush refuses (exit 5), and a
session listed in held-<source>.txt (a reboot's resume did not verify it) keeps its queue; ANCHOR_PUSH_FORCE=1 overrides both.

The inbox: after putting a line there this script waits a few seconds for the machine's confirmation, so the
answer is still "delivered" when the pane is live, and "inbox" when the line waits for its machine (asleep, or its puller
down: it goes out when that machine next asks). Cloud sessions are always delivered from here.
Stdlib only: called by anchor-hub, the stackshot server and the reboot hooks."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import glob
import json
import os
import re
import socket
import subprocess
import sys
import time

from stackshot.core import config as _cfg  # noqa: E402
from stackshot.fleet import inbox as _inbox  # noqa: E402  — label(): the `from:` line
from stackshot.fleet import sessions_registry as _sr  # noqa: E402  — a permanent session id → the session's name now

SRC = "msg" if os.environ.get("ANCHOR_PUSH_SOURCE") == "msg" else "hub"
A = str(_cfg.state("anchor-hub"))
Q = os.path.join(A, "queue-msg" if SRC == "msg" else "queue")
PAUSE = os.path.join(A, f"paused-{SRC}.json")
HELD = os.path.join(A, f"held-{SRC}.txt")
REG = os.path.expanduser("~/.claude/sessions")
CLAUDE = os.path.expanduser("~/.local/bin/claude")
PUB = str(_cfg.get("fleet", "publisher_letter") or "a")
CSE = re.compile(r"^cse_[A-Za-z0-9]{20,}$")    # a tagged id (24 characters after cse_), not a label such as cse_voice
FALLBACK_LOG = os.path.join(A, "push-fallback.jsonl")     # bridge: one line per drop labelled by caller(), the callers still to switch
INBOX_WAIT = float(os.environ.get("PUSH_INBOX_WAIT", "4"))      # s to wait for the machine's confirmation before answering "inbox"


def paused(name: str) -> bool:
    if os.environ.get("ANCHOR_PUSH_FORCE"):
        return False
    if os.path.exists(PAUSE):
        return True
    try:
        held = {ln.rstrip("\n") for ln in open(HELD, encoding="utf-8")}
        return name in held or bool(held and _sr.expand([name]) & _sr.expand_flag(held))     # a hold may list the session by its permanent id; an old name of it holds nothing else
    except Exception:
        return False


_SHELLS = re.compile(r"^(python[0-9.]*|bash|sh|dash|zsh|env|uv|uvx|node|bun|timeout|nohup|setsid|sudo)$")


def caller(pid: int | None = None) -> str:
    """The calling program's name when no sender was given: the parent process's script or command, its basename
    (python3 /…/release-job.py → release-job.py); a parent that is only an interpreter (python3 -c, a heredoc in a
    shell script) passes the question up to its own parent, three levels at most. Never refused: a caller not yet
    passing --from still delivers."""
    pid = pid or os.getppid()
    for _ in range(3):
        try:
            argv = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
            args = [a.decode(errors="replace") for a in argv if a]
        except Exception:
            break
        for a in args:
            b = os.path.basename(a)
            if a.startswith("-") or b in ("run", "--script") or _SHELLS.match(b):
                continue
            return b[:60]
        try:
            pid = int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[1])
        except Exception:
            break
        if pid <= 1:
            break
    return "an unnamed script"


def note_fallback(name: str, sender: str) -> None:
    """A drop that named no sender (no --from, no $PUSH_FROM) is recorded with the name caller() found, so the callers still
    to switch can be listed before require_sender goes on. Never in the way of the drop."""
    try:
        os.makedirs(A, exist_ok=True)
        with open(FALLBACK_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "to": name, "src": SRC, "caller": sender, "ppid": os.getppid()}) + "\n")
    except Exception:
        pass


def enqueue(name: str, text: str, sender: str = "") -> None:
    os.makedirs(Q, exist_ok=True)
    with open(os.path.join(Q, f"{name}.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.time(), "text": text, "from": sender}) + "\n")


def registry() -> list[dict]:
    out = []
    for f in glob.glob(os.path.join(REG, "*.json")):
        try:
            out.append(json.load(open(f, encoding="utf-8")))
        except Exception:
            continue
    return out


def alive(pid) -> bool:
    try:
        os.kill(int(pid), 0); return True
    except Exception:
        return False


def resolve(name: str) -> str:
    """name or transcript uuid → the socket of a live pane on this box ('' when none; the most recently updated wins)."""
    best = None
    for r in registry():
        if r.get("name") != name and r.get("sessionId") != name:
            continue
        pid, sock = r.get("pid"), r.get("messagingSocketPath")
        if not (pid and sock and os.path.exists(sock) and alive(pid)):
            continue
        if best is None or r.get("updatedAt", 0) > best[0]:
            best = (r.get("updatedAt", 0), sock)
    return best[1] if best else ""


def send(sock: str, text: str) -> bool:
    try:
        s = socket.socket(socket.AF_UNIX); s.settimeout(10)
        try:
            s.connect(sock)
            s.sendall((json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n").encode())
        finally:
            s.close()
        return True
    except Exception:
        return False


def cloud_send(cse: str, text: str) -> tuple[bool, str]:
    try:
        r = subprocess.run([CLAUDE, "--cloud", cse, "-p", text, "--output-format", "text"], capture_output=True, text=True, timeout=90)
        out = (r.stdout or "") + (r.stderr or "")
        return ("Sent to cloud session" in out), out
    except Exception as e:
        return False, str(e)


def inbox_serves(name: str) -> bool:
    """Does this pane's line wait in the inbox: the pane (a name or a transcript uuid) is listed on a machine whose puller
    is checking in, or on any machine other than this box (its puller, or its sessions' drain hooks, fetch what waits when
    they next ask; the server box reaches into no other machine since an earlier change). A pane listed on this box with no puller
    checking in, and a pane nobody lists, take the local path: the CLI's socket, else the queue anchor-hub flushes. The
    session and machine state is the view every reader uses (fleet.py); `online` is written by clients.py."""
    try:
        from stackshot.fleet import fleet
        from stackshot.fleet import liveness
        for L in fleet.letters():
            rows = fleet.read(L, "sessions")          # a session gone past the grace is an identity record, not a pane to wait for
            if any(liveness.present(v) and (u == name or v.get("name") == name) for u, v in rows.items()):
                return L != PUB or liveness.machine_online_ok(fleet.read(L, "machine"))
    except Exception:
        pass
    return False


def deliver_inbox(name: str, text: str, sender: str = "", ref: str = "") -> int:
    """A pane the inbox serves: the line waits in the server's inbox for the pane's machine. exit 0 delivered · 1 waiting. `ref` = the target as the caller wrote it
    (a permanent session id, a name, a transcript id): the inbox stores the permanent id it resolves to on the line; `name` is the address it was turned into."""
    inbox = _inbox
    iid = inbox.put(ref or name, text, SRC, sender=sender)
    if paused(name):
        print(f"queued (paused for a reboot) → {name}"); return 1
    t0 = time.time()
    while time.time() - t0 < INBOX_WAIT:
        if not inbox.exists(iid):
            print(f"delivered → {name}"); return 0
        time.sleep(0.2)
    print(f"inbox → {name}"); return 1


def deliver(name: str, text: str, sender: str = "") -> int:
    ref = name                      # as the caller wrote it: the inbox resolves it to the permanent id once
    name = _sr.delivery(name)       # a permanent session id is delivered to the session by the name it has now
    if not sender and _cfg.get("anchor_hub", "require_sender"):     # the end state, one config line away
        print("refused: no sender — pass --from <your name> (or set PUSH_FROM); every drop names who sent it", file=sys.stderr); return 2
    if not sender:
        sender = caller(); note_fallback(name, sender)
    if not CSE.match(name) and inbox_serves(name):
        return deliver_inbox(name, text, sender, ref)
    if paused(name):
        enqueue(name, text, sender); print(f"queued (paused for a reboot) → {name}"); return 1
    if CSE.match(name):
        ok, out = cloud_send(name, _inbox.label(sender, text))
        if ok:
            print(f"delivered (cloud) → {name}"); return 0
        print("cloud send failed: " + (out.strip().splitlines() or [""])[-1][:120], file=sys.stderr)
        enqueue(name, text, sender); print(f"queued → {name}"); return 1
    sock = resolve(name)
    if sock and send(sock, _inbox.label(sender, text)):
        print(f"delivered → {name}"); return 0
    enqueue(name, text, sender); print(f"queued → {name}"); return 1


def flush(name: str) -> int:
    name = _sr.delivery(name)
    qf = os.path.join(Q, f"{name}.jsonl")
    if not (os.path.exists(qf) and os.path.getsize(qf)):
        return 0
    if paused(name):
        print(f"paused or held ({SRC}): {name} keeps its queue", file=sys.stderr); return 5
    items = [_inbox.label(str(e.get("from") or ""), e["text"]) for e in (json.loads(ln) for ln in open(qf, encoding="utf-8") if ln.strip())]
    # the header says what kind of queue this is: the message queue holds stackshot messages, board relays and keeper
    # prompts, none of them an anchor change (a [board] notice arrived under "[anchor] 1 queued…")
    head = "[stackshot]" if SRC == "msg" else "[anchor]"
    text = f"{head} {len(items)} queued while you were away:\n" + "\n".join(items)
    if CSE.match(name):                     # a cloud session is retried at most once per rescan; a session that is gone keeps its queue
        ok, _ = cloud_send(name, text)
        if not ok:
            return 4
        os.remove(qf); print(f"flushed {len(items)} → {name} (cloud)"); return 0
    sock = resolve(name)
    if not sock:
        print(f"not live: {name}", file=sys.stderr); return 3
    if not send(sock, text):
        return 4
    os.remove(qf); print(f"flushed {len(items)} → {name}"); return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return 2
    if argv[0] == "--list":
        for r in sorted(registry(), key=lambda r: str(r.get("name") or "")):
            if alive(r.get("pid")):
                print(f"{str(r.get('name') or '?'):32} {str(r.get('status') or '?'):8} {r.get('messagingSocketPath') or ''}")
        return 0
    if argv[0] == "--flush":
        if len(argv) < 2:
            print("usage: push.py --flush <session>", file=sys.stderr); return 2
        return flush(argv[1])
    sender = os.environ.get("PUSH_FROM", "")
    if argv[0] == "--from":
        if len(argv) < 2:
            print(__doc__); return 2
        sender, argv = argv[1], argv[2:]
    if not argv or argv[0].startswith("-") or len(argv) < 2:
        print(__doc__); return 2
    return deliver(argv[0], argv[1], sender.strip())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
