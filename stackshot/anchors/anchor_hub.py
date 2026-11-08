"""anchor-hub — receive change events on a project's anchors and push a one-line notice into the sessions bound to them
(the session-anchors PRD in the config repo). The hub is anchorhub/core.py; the receivers are anchorhub/{slack,gworkspace,notion,github}.py
(one module each since an earlier change). Bindings come from the board store (board-data/anchors.json: a project's anchors →
its name line (`display-name:`), which the router stands in for, + the movers of its open items in scope) plus extra.json in the hub's state dir. Delivery goes through push.py.

  anchor-hub.py            run (systemd user service anchor-hub.service)
  anchor-hub.py status     print bindings + last events
  anchor-hub.py bindings   print the materialised anchor → sessions map
"""
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]
import json, os, sys, glob, signal, threading, time
# SIGHUP = systemctl --user reload anchor-hub.service (stackshot-reload.path): the main loop re-reads the config. Caught
# from here on, before the receivers' imports, so a reload while the hub starts is kept and never kills it.
HUP = threading.Event()
if __name__ == "__main__": signal.signal(signal.SIGHUP, lambda *_: HUP.set())

from stackshot.core import readonly as _ro
def standby() -> None:
    """STACKSHOT_READ_ONLY=1 (a warm standby copy): no receiver (no Slack socket, no Google, Notion or GitHub poll), no rescan, no
    delivery, no write to the board data or the hub's state. Only the hook port stays bound, 127.0.0.1:hook_port, and answers every request
    503 `standby (STACKSHOT_READ_ONLY)` (readonly.standby_hook_server), so the per-minute port check gets an HTTP answer. Runs before anything
    of the hub is imported, so nothing of it can start. Promotion = remove the drop-in and restart: the hub then starts as usual."""
    from stackshot.core import config as _c
    port = int(_c.get("anchor_hub", "hook_port") or 8010)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    srv = _ro.standby_hook_server(port)
    print(f"anchor-hub: read-only standby (STACKSHOT_READ_ONLY): no receivers; answering 503 on 127.0.0.1:{port}", file=sys.stderr, flush=True)
    while not stop.wait(timeout=60): HUP.clear()          # a reload (SIGHUP) has nothing to re-read here
    srv.shutdown()
    os._exit(0)
if __name__ == "__main__" and _ro.is_read_only() and (sys.argv[1] if len(sys.argv) > 1 else "run") == "run": standby()
from stackshot.anchors.anchorhub.core import Hub, ADIR, CTL, ENVF, MIRROR, RESCAN, STATUS, _cfg, load_bindings, log, now_iso, start_receiver
from stackshot.anchors.anchorhub import slack, gworkspace, notion, github

# ---------- main ----------
def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "bindings":
        for a, s in sorted(load_bindings().items()): print(f"{a:24} → {', '.join(sorted(s))}")
        return
    if cmd == "status":
        print(open(STATUS).read() if os.path.exists(STATUS) else "no status file (hub not running?)")
        return
    hub = Hub(); hub.rescan(); hub.hook_server()
    hub.status["receivers"] = {}
    # A receiver whose start fails on the network (DNS down at boot) is retried in the background by start_receiver, and its
    # hook routes answer 503 meanwhile. A failure for any other reason is final and logged at ERROR, as before.
    if os.path.exists(ENVF): start_receiver(hub, "slack", slack.run, lambda: True)      # connects asynchronously; its watch thread stamps the health each minute
    else: log.error("receiver slack: FAILED — no %s", ENVF); hub.status["receivers"]["slack"] = {"ok": False, "error": f"no {ENVF}", "checked": now_iso()}
    start_receiver(hub, "google", gworkspace.run, lambda: bool(hub.status.get("google")), routes=gworkspace.ROUTES)
    start_receiver(hub, "notion", notion.run, lambda: bool((hub.status.get("notion") or {}).get("ready")), routes=notion.ROUTES)
    start_receiver(hub, "github", github.run, lambda: bool(hub.status.get("github")))
    hub.write_status()
    hub.rescan()   # resolvers are registered now → label every bound anchor for the board
    # bindings: rebuild the moment the board mirror or extra.json changes (inotify); RESCAN is the fallback
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    dirty = threading.Event()
    class H(FileSystemEventHandler):
        def on_any_event(self, e):
            # Only a change counts. The watcher also reports a file being opened or closed, so the hub's own read of the store
            # started the next pass (a rescan twice a second instead of every RESCAN s). And in the hub's own
            # state dir only extra.json (bindings) and a pause flag (a lift flushes the queues) count: its status and read
            # positions are its own writes.
            if e.event_type not in ("modified", "created", "deleted", "moved"): return
            for p in (e.src_path, getattr(e, "dest_path", "")):
                if not p.endswith(".json"): continue
                if os.path.dirname(p) == ADIR and not (os.path.basename(p) == "extra.json" or os.path.basename(p).startswith("paused-")): continue
                dirty.set()
    obs = Observer()
    for d in glob.glob(f"{MIRROR}/?") + [MIRROR, ADIR]: obs.schedule(H(), d, recursive=False)   # MIRROR itself: anchors.json + projects.json
    obs.daemon = True; obs.start()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    os.makedirs(CTL, exist_ok=True)
    def serve_ctl():
        """Requests from anchor-hub-hook: {"verb": "catchup", "since": epoch} | {"verb": "persist"} → <id>.res.json."""
        for f in sorted(glob.glob(f"{CTL}/*.req.json")):
            try: req = json.load(open(f))
            except Exception: req = {}
            try: os.remove(f)
            except Exception: pass
            res = {"ok": True}
            try:
                if req.get("verb") == "catchup":
                    since = float(req["since"]); res["found"] = {}
                    for name, fn in list(hub.catchups.items()):
                        try: res["found"][name] = int(fn(since) or 0)
                        except Exception as e: res["ok"] = False; res.setdefault("errors", {})[name] = str(e)[:120]
                    hub.persist()
                elif req.get("verb") == "persist": res["saved"] = hub.persist()
                else: res = {"ok": False, "error": f"unknown verb {req.get('verb')!r}"}
            except Exception as e: res = {"ok": False, "error": str(e)[:200]}
            out = f[:-len(".req.json")] + ".res.json"; json.dump(res, open(out + ".tmp", "w")); os.replace(out + ".tmp", out)
    last = time.time(); last_save = time.time()
    while not stop.is_set():
        if dirty.wait(timeout=2): dirty.clear(); time.sleep(0.5); hub.rescan(); last = time.time()
        if HUP.is_set():                # a valid file is live at once (config.reload logs a broken one and what waits for a restart)
            HUP.clear(); changed = _cfg.reload()
            if changed is not None: log.info("config reload: %s", ", ".join(changed) or "no live setting changed")
        hub.tick()
        serve_ctl()
        if time.time() - last >= RESCAN: hub.rescan(); hub.write_status(); last = time.time()
        if time.time() - last_save >= 60: hub.persist(); last_save = time.time()     # a crash loses at most a minute of positions
    hub.shutdown()
    os._exit(0)

if __name__ == "__main__": main()
