"""The gbrain half of tests/home_brain_probe.py, run by the verify-gbrain harness inside its sandbox (it is not a stackshot suite). `journey(app)` is the
harness's contract; `app` is its connection to the harness's own brain, which this journey does not use for the list (see below).

Point 1 of the probe: a token minted with `--scopes read,write` lists no admin tool and no host-only tool. The rule is read from the gbrain source tree
that is running (its `operations` catalog: each tool's `scope`, `localOnly`, `cliOnly`), not typed in here, so a gbrain that changes a tool's scope is
caught the next time the probe runs.

Why a second brain: the harness's brain is embedded PGLite, which one process holds open, so `gbrain auth create` cannot mint a token while the harness's
`gbrain serve` runs. The journey makes a second throwaway brain of its own in the sandbox (own HOME, same steps as the harness), mints the read,write token
and a default one (admin rights) before it serves, serves it on another loopback port, lists the tools with each token and stops it by the PID it started.
Prints `PROBE-NAMES {json}` with the counts for the driver."""
import json, os, re, shutil, signal, socket, subprocess, time, urllib.request

BASE = os.environ["VG_BASE"]
SRC = os.path.join(BASE, "src")
CLI = ["bun", "--no-env-file", os.path.join(SRC, "src", "cli.ts")]
TOKEN_RE = re.compile(r"gbrain_[A-Za-z0-9_-]{16,}")
DUMP = ("import {operations} from './src/core/operations.ts';"
        "console.log('CATALOG' + JSON.stringify(operations.map(o => ({n: o.name, s: o.scope ?? null, l: !!o.localOnly, c: !!o.cliOnly, r: o.requiredScopes ?? []}))))")


def admin_tool(o):
    """A tool a read,write token may not call: its own scope is admin (or another beyond read and write: sources_add), or it also requires a scope beyond read and write (sources_add needs sources_admin)."""
    return (o["s"] or "read") not in ("read", "write") or any(x not in ("read", "write") for x in o["r"])


def catalog():
    p = subprocess.run(["bun", "--no-env-file", "-e", DUMP], cwd=SRC, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300)
    line = next((x for x in p.stdout.splitlines() if x.startswith("CATALOG")), None)
    return {o["n"]: o for o in json.loads(line[7:])} if line else {}


def run(env, *args):
    return subprocess.run([*CLI, *args], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=300, env=env)


def listed(port, token):
    """The names `tools/list` gives this token."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}/mcp", data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read().decode()
    msgs = [body] if body.startswith("{") else [x[6:] for x in body.split("\n") if x.startswith("data: ")]
    return sorted(t["name"] for m in msgs for t in json.loads(m).get("result", {}).get("tools", []))


def journey(app):
    ops = catalog()
    app.check("the source tree's tool catalog was read", len(ops) > 100, len(ops))
    home = os.path.join(BASE, "probe-home")
    os.makedirs(home)
    env = {**os.environ, "HOME": home, "GBRAIN_HOME": home}
    serve = None
    try:
        for args in (("init", "--pglite", "--no-embedding", "--non-interactive", "--git"), ("apply-migrations", "--yes", "--no-autopilot-install")):
            p = run(env, *args)
            app.check(f"second brain: gbrain {args[0]}", p.returncode == 0, (p.returncode, (p.stdout + p.stderr)[-400:]))
            if p.returncode:
                return
        tokens = {}
        for key, extra in (("rw", ["--scopes", "read,write"]), ("default", [])):
            p = run(env, "auth", "create", f"probe-{key}", *extra)
            found = TOKEN_RE.search(p.stdout)
            app.check(f"second brain: token minted ({key})", p.returncode == 0 and found, (p.returncode, p.stderr[-400:]))
            if not found:
                return
            tokens[key] = found.group()
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        serve = subprocess.Popen([*CLI, "serve", "--http", "--port", str(port), "--bind", "127.0.0.1", "--suppress-bootstrap-token"], env=env,
                                 stdout=open(os.path.join(home, "serve.log"), "wb"), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        up = False
        for _ in range(240):
            if serve.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
                    up = json.load(r).get("status") == "ok"
            except (OSError, ValueError):
                pass
            if up:
                break
            time.sleep(0.5)
        app.check("second brain: served over HTTP on loopback", up, serve.poll())
        if not up:
            return
        names, admin_names = listed(port, tokens["rw"]), listed(port, tokens["default"])
    finally:
        if serve is not None:
            serve.send_signal(signal.SIGTERM)
            try:
                serve.wait(timeout=60)
            except subprocess.TimeoutExpired:
                serve.kill()
                serve.wait()
        shutil.rmtree(home, ignore_errors=True)
    forbidden = sorted(n for n in names if n in ops and (admin_tool(ops[n]) or ops[n]["l"] or ops[n]["c"]))
    unknown = sorted(n for n in names if n not in ops)
    admin_only = {n for n, o in ops.items() if admin_tool(o) and not o["l"] and not o["c"]}
    eligible = {n for n, o in ops.items() if not admin_tool(o) and not o["l"] and not o["c"]}
    missing = sorted(eligible - set(names))
    app.say(f"PROBE read,write token lists {len(names)} tools; the default (admin-rights) token lists {len(admin_names)}; the catalog has {len(ops)} "
            f"({len(admin_only)} admin over the network, {sum(1 for o in ops.values() if o['l'])} host-only); read or write tools not listed: {len(missing)}")
    app.check("the read,write token lists no admin tool and no host-only tool", not forbidden, forbidden)
    app.check("every name it lists is a tool of the catalog", not unknown, unknown)
    gone = sorted(set(admin_names) - set(names))
    app.check("the default token lists more, the read,write list lies inside it, and what it lacks is admin tools only", len(names) > 0 and set(names) < set(admin_names)
              and all(admin_tool(ops[n]) for n in gone if n in ops), (len(names), len(admin_names), [n for n in gone if n in ops and not admin_tool(ops[n])]))
    app.say("PROBE-NAMES " + json.dumps({"count": len(names), "admin_count": len(admin_names), "missing": missing}))
