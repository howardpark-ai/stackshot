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

Where the server is. By default (`[client] push_mode = "local"`, or $ANCHOR_PUSH_MODE) this program runs on the server's own box and puts the line into the local inbox and queue
folders. On a box that is not the server's, those folders are nobody's: with `push_mode = "server"` (or "auto" and a client URL that is not this box: [client] url, <secrets>/client.url or
$STACKSHOT_URL) the line goes to the server through the client API's `message` call (client.py), with this box's token, and the server delivers it by its own rules (a message to a front agent
is refused unless it is for the person, a source is always the message's). The answer is then the server's: exit 0 delivered or held for the session, 1 waiting in the inbox,
2 refused (a refusal, no sender, or not passed on), 4 the server could not be reached, this box has no token yet, or the server's delivery failed (nothing was queued here: a caller that must not lose the line tries again). --flush has nothing to flush here: exit 0.
The server's own programs (server, minute, anchor-hub, audit, audit-run, router-live) set ANCHOR_PUSH_MODE=local for what they start.

Sources: ANCHOR_PUSH_SOURCE=hub (anchor-hub's notices, the default) or msg (the message tool and the prompts it carries), each
with its own queue dir and pause flag. While paused-<source>.json exists a delivery is queued and --flush refuses (exit 5), and a
session listed in held-<source>.txt (another tool's hold), held-resume-<source>.txt (a reboot's resume did not verify it) or held-api-<source>.txt (a hold made through the client API) keeps its queue; ANCHOR_PUSH_FORCE=1 overrides all.

Before a queued line is delivered (--flush, and the inbox's hand-out) it passes stale_notice.screen: a stall, wake, wait-ended or hand-off notice that is older than
[client] stale_notice_hours, or whose items have closed, been parked again or changed mover, is dropped, and of several about the same items only the newest goes.

The inbox: after putting a line there this script waits a few seconds for the machine's confirmation, so the
answer is still "delivered" when the pane is live, and "inbox" when the line waits for its machine (asleep, or its puller
down: it goes out when that machine next asks). Cloud sessions are always delivered from here.
Stdlib only: called by the anchors service, the stackshot server and the reboot hooks."""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

try:
    import fcntl
except ModuleNotFoundError:      # Windows has no flock: the file lock below is then not taken (a module the puller's box may import must load there)
    fcntl = None  # type: ignore[assignment]
import glob
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time

from stackshot.core import config as _cfg  # noqa: E402
from stackshot.fleet import fleet as _fleet  # noqa: E402  — publisher(): the box that runs this server
from stackshot.fleet import inbox as _inbox  # noqa: E402  — label(): the `from:` line
from stackshot.fleet import stale_notice as _stale  # noqa: E402  — the screen a queued notice passes before delivery
from stackshot.fleet import sessions_registry as _sr  # noqa: E402  — a permanent session id → the session's name now

SRC = "msg" if os.environ.get("ANCHOR_PUSH_SOURCE") == "msg" else "hub"
KIND = _inbox.clean_kind(os.environ.get("ANCHOR_PUSH_KIND"))     # the front gate's kind of the notice this process pushes (telling.tell_woken sets it): stored on the line, "" for a sender that gives none
A = str(_cfg.state("anchor-hub"))
Q = os.path.join(A, "queue-msg" if SRC == "msg" else "queue")
PAUSE = os.path.join(A, f"paused-{SRC}.json")
HELD = os.path.join(A, f"held-{SRC}.txt")                   # another tool's holds
HELD_RESUME = os.path.join(A, f"held-resume-{SRC}.txt")     # a reboot's resume's holds; a key in any of the three files holds
HELD_API = os.path.join(A, f"held-api-{SRC}.txt")           # the client API's holds (inbox_holds.py writes only this file)
REG = os.path.expanduser("~/.claude/sessions")
CLAUDE = os.path.expanduser("~/.local/bin/claude")
PUB = _fleet.publisher()                        # the box that runs this server: [fleet] publisher_letter, else found from the hostname
CSE = re.compile(r"^cse_[A-Za-z0-9]{20,}$")    # a tagged id (24 characters after cse_), not a label such as cse_voice
FALLBACK_LOG = os.path.join(A, "push-fallback.jsonl")     # bridge: one line per drop labelled by caller(), the callers still to switch
INBOX_WAIT = float(os.environ.get("PUSH_INBOX_WAIT", "4"))      # s to wait for the machine's confirmation before answering "inbox"


def paused(name: str, src: str | None = None) -> bool:
    """Is a delivery to `name` paused or held? Of this process's own source (ANCHOR_PUSH_SOURCE), or of `src` ("hub" or "msg") when a caller asks for the other: anchor-hub asks it of both queues without starting a process for each."""
    pause, files = PAUSE, (HELD, HELD_RESUME, HELD_API)
    if src is not None and src != SRC:
        pause, files = os.path.join(A, f"paused-{src}.json"), tuple(os.path.join(A, f"{k}-{src}.txt") for k in ("held", "held-resume", "held-api"))
    if os.environ.get("ANCHOR_PUSH_FORCE"):
        return False
    if os.path.exists(pause):
        return True
    held: set[str] = set()
    for f in files:         # the union of the three files; one that cannot be read (missing) lists nothing
        try:
            held |= {ln.rstrip("\n") for ln in open(f, encoding="utf-8")}
        except Exception:
            pass
    try:
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


class _queue_lock:
    """One lock for the queue directory: an append and the rewrite that drops stale lines never interleave (a line appended while a rewrite runs would be lost)."""
    def __enter__(self):
        os.makedirs(Q, exist_ok=True)
        self.f = open(os.path.join(Q, ".lock"), "w")
        if fcntl is not None:
            fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        if fcntl is not None:
            fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()
        return False


def enqueue(name: str, text: str, sender: str = "") -> None:
    with _queue_lock():
        with open(os.path.join(Q, f"{name}.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "text": text, "from": sender, **({"kind": KIND} if KIND else {})}) + "\n")      # a row with no kind is read as it always was (inbox.kind_of)


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
    iid = inbox.put(ref or name, text, SRC, sender=sender, kind=KIND)
    if paused(name):
        print(f"queued (paused for a reboot) → {name}"); return 1
    t0 = time.time()
    while time.time() - t0 < INBOX_WAIT:
        if not inbox.exists(iid):
            print(f"delivered → {name}"); return 0
        time.sleep(0.2)
    print(f"inbox → {name}"); return 1


def retired(name: str, text: str, sender: str) -> str:
    """A message-source line for a name that is no live session (a retired agent, an old name, a name nobody runs) is not left in the queue: retired_recipient hands it to the project's router, or
    returns it to its sender, and answers the one line that says so ("" = as before: the name may be live, or anything failed, and the caller queues it)."""
    if SRC != "msg" or os.environ.get("ANCHOR_PUSH_FORCE"):
        return ""
    try:
        from stackshot.fleet import retired_recipient as _rr
        res = _rr.handle(name, text, sender, deliver=deliver)
        return res.line if res else ""
    except Exception:
        return ""


def _is_this_box(host: str) -> bool:
    """Does a client URL's host name this box: a loopback or unspecified address (127.x, ::1, 0.0.0.0, ::), localhost, this box's host name or its fully qualified name (any case), or the bare
    first label of either. A dotted name must be the whole host or fully qualified name: another domain's `<label>.example.org` is not this box because its first label is."""
    h = host.strip().strip("[]").split("%")[0].rstrip(".").lower()
    if not h:
        return False
    try:
        ip = ipaddress.ip_address(h)
        return ip.is_loopback or ip.is_unspecified
    except ValueError:
        pass
    if h == "localhost" or h.endswith(".localhost"):
        return True
    names = {n.strip().rstrip(".").lower() for n in (socket.gethostname(), socket.getfqdn()) if n}
    return h in names or ("." not in h and h in {n.split(".")[0] for n in names})


_warned: list[str] = []


def _warn_once(why: str) -> None:
    """One warning line on stderr per process about the push settings (the first problem met): the line still goes by the safe default, the local folders."""
    if not _warned:
        _warned.append(why)
        print(f"push.py: {why}; delivering to the local folders", file=sys.stderr)


def server_mode() -> bool:
    """Is the line sent to the server through the client API: $ANCHOR_PUSH_MODE, else [client] push_mode: "local" (the default) no · "server" yes · "auto" yes when the client URL names another machine
    (a host that is not this box: see _is_this_box), as it does on a box that is not the server's. A mode that is none of the three, or an "auto" whose client URL gives no host, is local with one
    warning line on stderr for the process."""
    mode = (os.environ.get("ANCHOR_PUSH_MODE") or str(_cfg.get("client", "push_mode", default="local") or "local")).strip().lower()
    if mode == "server":
        return True
    if mode == "auto":
        url = ""
        try:
            from urllib.parse import urlparse
            from stackshot.fleet import client as _client
            url = _client.server_url()
            host = (urlparse(url).hostname or "").lower()
        except Exception:
            host = ""
        if not host:
            if url:
                _warn_once("push_mode auto could not read a host from the client URL")
            return False
        return not _is_this_box(host)
    if mode != "local":
        _warn_once(f"push_mode {mode[:40]!r} is none of local, server or auto")
    return False


def deliver_server(name: str, text: str, sender: str = "") -> int:
    """The line goes to the server (client.py's message call) → the exit code in the header. The server's answer is printed as the other paths print theirs."""
    if not sender and _cfg.get("anchor_hub", "require_sender"):
        print("refused: no sender — pass --from <your name> (or set PUSH_FROM); every drop names who sent it", file=sys.stderr); return 2
    if not sender:
        sender = caller()
    from stackshot.fleet import client as _client
    status, out = _client.message(name, text, sender)
    if status == 200:
        print(out); return 1 if out.startswith(("inbox", "queued")) else 2 if out.startswith("not passed on") else 0
    if not 400 <= status < 500:
        print(f"server not reached [{status}]: {out}", file=sys.stderr); return 4
    if out.startswith(("no token on this machine", "Delivery failed")):     # not a refusal of the line: this box has no token yet, or the server's delivery failed: a later try can succeed
        print(f"not delivered [{status}]: {out}", file=sys.stderr); return 4
    print(f"refused by the server [{status}]: {out}", file=sys.stderr)
    return 2


def deliver(name: str, text: str, sender: str = "") -> int:
    if server_mode():
        return deliver_server(name, text, sender)
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
    said = retired(name, text, sender)
    if said:
        print(said); return 1
    enqueue(name, text, sender); print(f"queued → {name}"); return 1


def flush_held(name: str, src: str) -> bool:
    """Would `--flush name` of source `src` stop at its first check (exit 5: paused or held), having done nothing? anchor-hub skips the process then; the same test `flush` makes."""
    return paused(_sr.delivery(name), src)


def flush(name: str, digest: "_inbox.Digest | None" = None) -> int:
    """Deliver what is queued for `name` as one turn. `digest` is the server's ruling on the queued lines (inbox.filed_as_fyi): lines it files as an fyi are dropped from the queue and start no turn. The script
    (`--flush`) has none: it runs apart from the server, which holds the hooks that rule, so it hands the lines out as it always did."""
    if server_mode():
        return 0                    # no queue here: the server holds every line
    name = _sr.delivery(name)
    qf = os.path.join(Q, f"{name}.jsonl")
    if not (os.path.exists(qf) and os.path.getsize(qf)):
        return 0
    if paused(name):
        print(f"paused or held ({SRC}): {name} keeps its queue", file=sys.stderr); return 5
    with _queue_lock():         # a notice that is no longer true is dropped before anything is sent, also for a session that is not live (its queue would otherwise only grow)
        rows = [json.loads(ln) for ln in open(qf, encoding="utf-8") if ln.strip()]
        keep, dropped = _stale.screen(rows, [name])
        if dropped:
            for _row, why in dropped:
                print(f"dropped a stale notice for {name}: {why}")      # stdout: the sender's retry logs a flush's stdout, never its stderr
            if keep:
                tmp = qf + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write("".join(json.dumps(r) + "\n" for r in keep))
                os.replace(tmp, qf)
            else:
                os.remove(qf)
    if not keep:
        print(f"dropped {len(dropped)} stale → {name}"); return 0
    head = "[stackshot]" if SRC == "msg" else "[anchor]"      # the header says what kind of queue this is: the message queue holds stackshot messages, board relays and keeper prompts, none of them an anchor change (a [board] notice arrived under "[anchor] 1 queued…")
    items = [_inbox.label(str(e.get("from") or ""), e["text"]) for e in keep]
    filed = _inbox.filed_as_fyi(digest, name, items, [_inbox.kind_of(e) for e in keep])      # no line asks him for anything and he is not there for this pane: those lines ride its next turn, they start none
    if filed:
        left = [e for i, e in enumerate(keep) if i not in set(filed)]      # a failed filing leaves the lines it did not reach: they go out as a turn, the filed ones never twice
        with _queue_lock():
            if left:
                tmp = qf + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write("".join(json.dumps(r) + "\n" for r in left))
                os.replace(tmp, qf)
            else:
                os.remove(qf)
        print(f"filed {len(filed)} as an fyi → {name}")
        if not left:
            return 0
        keep = left; items = [_inbox.label(str(e.get("from") or ""), e["text"]) for e in keep]
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
