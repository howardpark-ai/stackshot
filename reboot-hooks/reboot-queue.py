#!/usr/bin/env python3
"""reboot-queue.py — the resume half shared by anchor-hub-hook and stackshot-hook (contract: salamander
docs/reboot-contract.md, version 1).

  reboot-queue.py resume --source hub|msg --sessions <file>   deliver queued items, oldest first, to the verified sessions
  reboot-queue.py count  --source hub|msg                      queued items and sessions (for status and flush-stop)

<file> lists the Claude transcript uuids the fleet tool verified as resumed and bridged, one per line. A queue belongs to a session
key (a uuid or a pane name). It is delivered when its key is a listed uuid or that uuid's pane name, or when the session is
not on this box at all (a cloud cse_… session, a pane on another machine: the reboot did not touch them). Every other queue on this box
is held: its key goes to <state>/anchor-hub/held-<source>.txt, and anchor-relay keeps it queued until a later resume
lists it. Prints one JSON line; exit 0 when every deliverable queue was delivered.
"""
import glob, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import config as _cfg  # noqa: E402  (stackshot.toml)
import interp as _interp  # noqa: E402  (a missing interpreter never stops a delivery)
A = str(_cfg.state("anchor-hub"))
FLEET = str(_cfg.fleet_dir())
PUB = str(_cfg.get("fleet", "publisher_letter") or "a")
PUSH = [sys.executable, os.path.join(HERE, "..", "push.py")]


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


def resume_inbox(src, listed, fl):
    """The inbox (where every line for another machine waits, since an earlier change the only path there): nothing is pushed from here. The lines of the verified sessions are released (inbox.take hands them out
    although the source is still paused), every other key on this box is held, and this waits for the pullers to confirm.
    → the counts, in the shape the push path reports."""
    import time
    import inbox
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
    return {"delivered": want - left, "to": {k for k in go if k not in left_by}, "held": sum(q[k] for k in held_keys), "held_keys": held_keys,
            "waiting": left, "waiting_sessions": sorted(left_by)}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    src = arg("--source", "hub"); src = "msg" if src == "msg" else "hub"
    q = queues(src)
    import inbox
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
    delivered = held = failed = 0; to, held_keys, failed_keys = set(), [], []
    env = {**os.environ, "ANCHOR_PUSH_SOURCE": src, "ANCHOR_PUSH_FORCE": "1"}
    for key, n in q.items():                     # the push queue: cloud sessions, and panes on this box that were not live
        go = key in allowed or key.startswith("cse_") or (key in elsewhere and key not in here_keys)
        if not go:
            held += n; held_keys.append(key); continue
        r = subprocess.run([*_interp.resilient(PUSH), "--flush", key], capture_output=True, text=True, env=env, timeout=150)
        if r.returncode == 0: delivered += n; to.add(key)
        else: failed += n; failed_keys.append(key)
    ib = resume_inbox(src, listed, fl)
    delivered += ib["delivered"]; to |= ib["to"]; held += ib["held"]; held_keys += ib["held_keys"]
    extra = {"waiting": ib["waiting"], "waiting_sessions": ib["waiting_sessions"]}
    hf = os.path.join(A, f"held-{src}.txt")
    tmp = hf + ".tmp"; open(tmp, "w").write("".join(k + "\n" for k in held_keys)); os.replace(tmp, hf)
    print(json.dumps({"ok": failed == 0, "delivered": delivered, "sessions": len(to), "held": held, "held_sessions": held_keys,
                      "failed": failed, "failed_sessions": failed_keys, **extra}))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
