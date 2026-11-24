#!/usr/bin/env python3
"""reboot-queue.py — the resume half shared by anchor-hub-hook and stackshot-hook (contract: salamander
docs/reboot-contract.md, version 1).

  reboot-queue.py resume --source hub|msg --sessions <file>   deliver queued items, oldest first, to the verified sessions
  reboot-queue.py count  --source hub|msg                      queued items and sessions (for status and flush-stop)

<file> lists the Claude transcript uuids the fleet tool verified as resumed and bridged, one per line. A queue belongs to a session
key (a uuid or a pane name). It is delivered when its key is a listed uuid or that uuid's pane name, or when the session is
not on this box at all (a cloud cse_… session, a pane on another machine: the reboot did not touch them). Every other queue on this box
is held: its key goes to <state>/anchor-hub/held-resume-<source>.txt (this file is the resume's own: the fleet tool writes
held-<source>.txt, and neither writer touches the other's file; stackshot reads the union of the two), and the line stays queued until a
later resume lists it. A key no session row names anywhere (neither a fleet heartbeat nor the session registry) is a retired session: it is
left out of the file and listed as retired_sessions. A key an earlier resume held and this one did not verify nor find queued stays held, but not for good: the server's minute sweep lifts a key that stayed in the file
longer than [client] resume_hold_max_hours (default 6) since it was first seen there (inbox_holds.sweep_resume; the queued lines stay in the inbox), and a resume that finds the key
queued and cannot verify it holds it afresh, which starts that age again.
Prints one JSON line; exit 0 when every deliverable queue was delivered.
"""
import contextlib, glob, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from stackshot.core import config as _cfg  # noqa: E402  (stackshot.toml)
from stackshot.core import interp as _interp  # noqa: E402  (a missing interpreter never stops a delivery)
from stackshot.fleet import fleet as _fleet  # noqa: E402  (the box that runs this server)
A = str(_cfg.state("anchor-hub"))
FLEET = str(_cfg.fleet_dir())
PUB = _fleet.publisher()
PUSH = [sys.executable, os.path.join(HERE, "..", "stackshot", "fleet", "push.py")]


def arg(name, default=None):
    a = sys.argv
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else default


def qdir(src): return os.path.join(A, "queue-msg" if src == "msg" else "queue")


def queues(src):
    out = {}
    for f in sorted(glob.glob(os.path.join(qdir(src), "*.jsonl"))):
        try: n = sum(1 for l in open(f, encoding="utf-8") if l.strip())
        except Exception: n = 0
        if n: out[os.path.basename(f)[:-6]] = n
    return out


def fleet_sessions():
    """letter → {uuid: name} from the session and machine state the server keeps of its clients (fleet.py)."""
    out = {}
    for f in glob.glob(os.path.join(FLEET, "*", "sessions.json")):
        try: out[os.path.basename(os.path.dirname(f))] = {k: (v or {}).get("name", "") for k, v in json.load(open(f, encoding="utf-8")).items()}
        except Exception: pass
    return out


def lines_of(path):
    try: return {l.strip() for l in open(path, encoding="utf-8") if l.strip()}
    except Exception: return set()


def has_row(key, fl):
    """Does any session row name this key: a fleet heartbeat row (its uuid or its name, on any machine) or a row of the session registry
    (permanent id, transcript id, name or alias; a retired row is still a row)? A key none names is a retired session.
    A fleet heartbeat match decides first. The registry's load never raises: a folder missing or unreadable gives it no rows at all, and with
    none the answer is unknown, not retired, so the key is kept (never every hold dropped for want of a registry)."""
    if any(key in m or key in m.values() for m in fl.values()): return True
    from stackshot.fleet import sessions_registry as sr
    reg = sr.load(); low = key.lower()
    if not reg.rows: return True
    return low in reg.rows or low in reg.by_transcript or key in reg.by_name


def resume_inbox(src, listed, fl):
    """The inbox (where every line for another machine waits, since an earlier change the only path there): nothing is pushed from here. The lines of the verified sessions are released (inbox.take hands them out
    although the source is still paused), every other key on this box is held, and this waits for the pullers to confirm.
    → the counts, in the shape the push path reports."""
    import time
    from stackshot.fleet import inbox
    here = fl.get(PUB, {})
    elsewhere = {k for L, m in fl.items() if L != PUB for k in m} | {n for L, m in fl.items() if L != PUB for n in m.values() if n}
    allowed = listed | {here.get(u) for u in listed if here.get(u)}
    here_keys = set(here) | {n for n in here.values() if n}
    q = inbox.waiting(src)
    go = {k for k in q if k in allowed or (k in elsewhere and k not in here_keys)}
    held_keys = sorted(k for k in q if k not in go)
    p = os.path.join(A, f"release-{src}.txt"); open(p + ".tmp", "w").write("".join(k + "\n" for k in sorted(go))); os.replace(p + ".tmp", p)
    want = sum(q[k] for k in go); wait = float(arg("--wait", "30")); t0 = time.time()
    while want and time.time() - t0 < wait:
        if not any(k in go for k in inbox.waiting(src)): break
        time.sleep(1)
    left_by = {k: n for k, n in inbox.waiting(src).items() if k in go}
    try: os.remove(p)
    except FileNotFoundError: pass
    left = sum(left_by.values())
    # a line still waiting is not lost: its session's machine has not asked yet (asleep, or its puller is down). It is
    # reported as waiting, not as failed, and goes out when that machine next asks.
    return {"delivered": want - left, "to": {k for k in go if k not in left_by}, "held": sum(q[k] for k in held_keys), "held_keys": held_keys, "held_by": {k: q[k] for k in held_keys},
            "waiting": left, "waiting_sessions": sorted(left_by)}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    src = arg("--source", "hub"); src = "msg" if src == "msg" else "hub"
    q = queues(src)
    from stackshot.fleet import inbox
    if cmd == "count":
        w = inbox.waiting(src)
        print(json.dumps({"items": sum(q.values()) + sum(w.values()), "sessions": len(set(q) | set(w))})); return 0
    if cmd != "resume": print(__doc__); return 2
    listed = set()
    try: listed = {l.strip() for l in open(arg("--sessions", ""), encoding="utf-8") if l.strip()}
    except Exception as e: print(json.dumps({"ok": False, "error": f"cannot read --sessions: {e}"})); return 1
    fl = fleet_sessions(); here = fl.get(PUB, {})
    elsewhere = {k for L, m in fl.items() if L != PUB for k in m} | {n for L, m in fl.items() if L != PUB for n in m.values() if n}
    allowed = listed | {here.get(u) for u in listed if here.get(u)}
    here_keys = set(here) | {n for n in here.values() if n}
    delivered = held = failed = 0; to, held_keys, failed_keys = set(), [], []; held_by = {}
    def deliverable(k):                          # the one test the push queue and the kept holds share: a key the reboot did not touch, or one a resume verified
        return k in allowed or k.startswith("cse_") or (k in elsewhere and k not in here_keys)
    env = {**os.environ, "ANCHOR_PUSH_SOURCE": src, "ANCHOR_PUSH_FORCE": "1", "ANCHOR_PUSH_MODE": "local"}     # local: this flushes this box's own queue, and a server-mode flush exits 0 without flushing
    for key, n in q.items():                     # the push queue: cloud sessions, and panes on this box that were not live
        go = deliverable(key)
        if not go:
            held += n; held_keys.append(key); held_by[key] = n; continue
        r = subprocess.run([*_interp.resilient(PUSH), "--flush", key], capture_output=True, text=True, env=env, timeout=150)
        if r.returncode == 0: delivered += n; to.add(key)
        else: failed += n; failed_keys.append(key)
    ib = resume_inbox(src, listed, fl)
    delivered += ib["delivered"]; to |= ib["to"]; held += ib["held"]; held_keys += ib["held_keys"]; held_by.update(ib["held_by"])
    extra = {"waiting": ib["waiting"], "waiting_sessions": ib["waiting_sessions"]}
    # The resume's own hold file only (held-<src>.txt is the fleet tool's). It keeps a key an earlier resume held that this run neither
    # verified nor found queued, so a hold is never lost for want of a queued line; a key no session row names is retired and is not kept.
    # The read and the write of the file are one step under the lock the server's minute sweep takes to lift a key that stayed past [client] resume_hold_max_hours (inbox_holds.sweep_resume), so
    # neither overwrites the other; a key found queued and not verified is held afresh and starts its age again, a key only kept keeps the age it has.
    hf = os.path.join(A, f"held-resume-{src}.txt")
    stack = contextlib.ExitStack(); inbox_holds = None       # no lock, no side file: the hold file itself is still written, as it was before the lock existed
    try:
        from stackshot.fleet import inbox_holds as _ih
        stack.enter_context(_ih.locked()); inbox_holds = _ih
    except Exception as e: print(f"resume: hold file written without the lock: {e.__class__.__name__}: {e}", file=sys.stderr)    # never stops a resume
    with stack:
        keep = set(held_keys) | {k for k in lines_of(hf) if not deliverable(k)}
        retired = sorted(k for k in keep if not has_row(k, fl))
        dropped = set(retired)
        held_keys = [k for k in held_keys if k not in dropped]
        held = sum(n for k, n in held_by.items() if k not in dropped)
        tmp = hf + ".tmp"; open(tmp, "w").write("".join(k + "\n" for k in sorted(keep - dropped))); os.replace(tmp, hf)
        if inbox_holds:
            try: inbox_holds.resume_restart(src, held_keys)
            except Exception as e: print(f"resume: ages of the held keys not recorded: {e.__class__.__name__}: {e}", file=sys.stderr)    # never stops a resume
    print(json.dumps({"ok": failed == 0, "delivered": delivered, "sessions": len(to), "held": held, "held_sessions": held_keys,
                      "retired_sessions": retired, "failed": failed, "failed_sessions": failed_keys, **extra}))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
