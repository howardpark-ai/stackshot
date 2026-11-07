"""versions.py — installed vs latest for the Machines panel.

The packages come from stackshot.toml [machines_panel]: `installed = "fleet"` (one version per machine, from the machine.json
`claude` of the session and machine state the server keeps of its clients (clients.py, fleet.py), the publisher's own from
`self_cmd`) or `"cmd:<command>"` (this box; the first version-shaped token the command prints); `latest = "npm:<package>"` or
`"github-release:<owner/repo>"`; `machines = [letters]` where a host-only package runs.
A machine is online while its puller checks in, within [client] online_minutes (machine.json `online`, written by clients.py),
else "offline since" its last check-in; a machine with no puller on record is offline since it was last seen. The publisher is
always live. (The ssh probe of the fleet-state writer, and `[client] liveness`, were removed.)
Machines with no sala fleet letter (such as spare-box) are listed in [machines_panel] `ssh_hosts`: the publisher reads each over
one `ssh -o BatchMode=yes` call per refresh (ssh_hosts_read) that prints every package's version command, a package's `ssh_cmd`, else its
`cmd:` command, else its `self_cmd`; a package the host does not have gives no version and so no row. The result is cached in
versions.ssh.json and refreshed by a forced write (the timer publish, every [publish] every_minutes, and a bump) or when older than
SSH_CACHE_MIN; a write-triggered publish in between reads the cache. An unreachable host keeps its last versions and is marked so.
A listed host that is also a fleet machine (same full hostname) is drawn as that machine's one card, not a second (render.py): this module still reads it.
Output: <state>/site/versions.json
{"checked", "packages": [{name, installed, latest, state, machines?, machine_state?}], "ssh_hosts"?: [{name, reachable, checked, last_ok?, packages: {name: version}}]}. The latest lookups (network) are cached CACHE_MIN minutes in versions.latest.json;
write(force=True) refreshes them. Installed versions are read on every call (cheap, no network)."""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

import config as _cfg
import fleet as _fleet

OUT: Path = _cfg.state("site", "versions.json")
LATEST: Path = _cfg.state("site", "versions.latest.json")
CACHE_MIN = 15
SSH_OUT: Path = _cfg.state("site", "versions.ssh.json")
SSH_CACHE_MIN = 15           # a cached ssh read older than this is read again by a write that is not forced (a stalled timer)
SSH_TIMEOUT = 10             # s: the whole ssh call per host (ConnectTimeout 5 inside it)
ZONE = _cfg.tz()


def _pub() -> str:          # the publisher's letter, read at use (a reload is live)
    return str(_cfg.get("fleet", "publisher_letter") or "a")


def _run(cmd: list[str], timeout: int = 20, env: dict | None = None) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _norm(v: str | None) -> str:
    return (v or "").strip().lstrip("v")


def _vt(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.split("."))
    except Exception:
        return (0,)


def _latest(spec: str) -> str:
    kind, _, arg = str(spec).partition(":")
    if kind == "npm":
        out = _run(["/usr/bin/npm", "view", arg, "version"])
        return out.splitlines()[-1] if out else ""
    if kind == "github-release":
        return _run(["gh", "release", "view", "--repo", arg, "--json", "tagName", "-q", ".tagName"])
    return ""


def latest_all(force: bool = False) -> dict[str, str]:
    """name → latest version, from the cache unless it is older than CACHE_MIN or force; a failed lookup keeps the old value."""
    try:
        prev = json.load(open(LATEST, encoding="utf-8"))
    except Exception:
        prev = {}
    fresh = LATEST.exists() and time.time() - LATEST.stat().st_mtime < CACHE_MIN * 60
    if (fresh and not force) or not _cfg.get("machines_panel", "latest_lookups", default=True):
        return prev                              # latest_lookups = false: an instance that asks no outside service (a staging copy)
    out = dict(prev)
    for pk in _cfg.get("machines_panel", "packages") or []:
        if pk.get("latest"):
            v = _latest(pk["latest"])
            if v:
                out[pk["name"]] = v
    LATEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = LATEST.with_suffix(".tmp"); json.dump(out, open(tmp, "w", encoding="utf-8")); os.replace(tmp, LATEST)
    return out


_VER = re.compile(r"\d+\.\d+(?:\.[\w-]+)*")


def _installed_cmd(cmd: str) -> str:
    """The first version-shaped token the command prints ("1.2.3 (Tool)" → 1.2.3; "mytool 0.1.2.3" → 0.1.2.3)."""
    parts = [os.path.expanduser(x) for x in shlex.split(cmd)]
    env = dict(os.environ); d = os.path.dirname(parts[0])
    if d: env["PATH"] = d + os.pathsep + env.get("PATH", "")   # a `#!/usr/bin/env bun` script finds its runtime next to it, whatever PATH the unit has
    out = _run(parts, env=env)                                 # (the gbrain card read "?" under the service's PATH)
    m = _VER.search(out or "")
    return _norm(m.group(0)) if m else ""


def _remote(script: str) -> str:
    """The command string ssh hands to the host's login shell: `sh -c '<script>'`, so a login shell that is not POSIX (fish, csh) still runs it."""
    return "sh -c " + shlex.quote(script)


def _ssh(host: str, script: str, timeout: int = SSH_TIMEOUT) -> tuple[int, str]:
    """(exit code, stdout) of `script` run on `host` over ssh with key auth only: no prompt, no shared connection (a stale ControlMaster socket
    cannot hang or answer for it), a dead link noticed in about 6 s, `--` before the host. 255 = ssh itself failed (unreachable, refused,
    timed out). The one place that talks ssh: tests replace it."""
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "ControlMaster=no", "-o", "ControlPath=none",
                            "-o", "ServerAliveInterval=3", "-o", "ServerAliveCountMax=2", "--", host, _remote(script)],
                           capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout
    except Exception:
        return 255, ""


def _ssh_cmd(pk: dict) -> str:
    """The command that prints package pk's version on an ssh host: its `ssh_cmd`, else the `cmd:` command, else `self_cmd`."""
    if pk.get("ssh_cmd"):
        return str(pk["ssh_cmd"])
    spec = str(pk.get("installed") or "")
    if spec.startswith("cmd:"):
        return spec[4:]
    return str(pk.get("self_cmd") or "")


def _ssh_script(cmds: list[tuple[int, str]]) -> str:
    """One remote script for all packages: `@@<i>` then the output of command i (stderr dropped), each in its own subshell with its
    executable's directory on PATH (a `#!/usr/bin/env bun` script finds bun next to it, as _installed_cmd does here). The commands go to the
    remote shell as written, so `~` is the remote home. It ends in `true`, so it exits 0 wherever it ran: any non-zero exit (ssh's own 255,
    or a shell that could not run it) counts as unreachable."""
    parts = []
    for i, c in cmds:
        exe = c.split()[0]
        parts.append(f"printf '@@{i}\\n'; ( p={exe}; case $p in */*) PATH=\"${{p%/*}}:$PATH\";; esac; {c} ) 2>/dev/null")
    return "; ".join(parts) + "; true"


def _ssh_parse(out: str, names: dict[int, str]) -> dict[str, str]:
    """name → version from _ssh_script's output; a package whose command printed no version-shaped token is left out."""
    res: dict[str, str] = {}; cur = None; buf: list[str] = []
    def flush():
        if cur is not None:
            m = _VER.search("\n".join(buf))
            if m and cur in names:
                res[names[cur]] = _norm(m.group(0))
    for ln in (out or "").splitlines():
        m = re.fullmatch(r"@@(\d+)", ln.strip())
        if m:
            flush(); cur = int(m.group(1)); buf = []
        else:
            buf.append(ln)
    flush()
    return res


def ssh_hosts_read(force: bool = False) -> list[dict]:
    """[machines_panel] ssh_hosts, in config order: {name, reachable, checked, last_ok?, packages: {name: version}}. One ssh call per host
    (the hosts in parallel, each under SSH_TIMEOUT), cached in versions.ssh.json: read again on force, for a host not in the cache, or when
    the cache is older than SSH_CACHE_MIN. An unreachable host keeps the versions it last had and `last_ok` says when it last answered."""
    cfg = _cfg.get("machines_panel", "ssh_hosts") or []
    if isinstance(cfg, str):
        cfg = [cfg]                                          # one host written as a string
    hosts: list[str] = []
    for h in cfg:
        h = str(h).strip()
        if not h or h.startswith("-") or re.search(r"\s", h):
            print(f"versions: ssh host {h!r} ignored (empty, starts with '-' or holds whitespace)", file=sys.stderr); continue
        if h not in hosts: hosts.append(h)
    if not hosts:
        return []
    pkgs = list(_cfg.get("machines_panel", "packages") or [])
    cmds = [(i, _ssh_cmd(pk)) for i, pk in enumerate(pkgs) if _ssh_cmd(pk).strip()]
    names = {i: pkgs[i]["name"] for i, _ in cmds}
    script = _ssh_script(cmds) if cmds else ""
    try:
        prev = json.load(open(SSH_OUT, encoding="utf-8"))
    except Exception:
        prev = {}
    if not isinstance(prev, dict):
        prev = {}
    prev = {h: e for h, e in prev.items() if isinstance(e, dict)}   # a damaged cache entry is as good as none
    now = time.time()
    def stale(h: str) -> bool:
        try: return now - float(prev[h].get("ts", 0)) >= SSH_CACHE_MIN * 60
        except Exception: return True
    due = [h for h in hosts if force or h not in prev or stale(h)]
    def probe(h: str) -> dict:
        t = dt.datetime.now(ZONE).strftime("%Y-%m-%d %H:%M %Z")
        old = prev.get(h) or {}
        try:
            rc, out = _ssh(h, script) if script else (255, "")
            if rc == 0:
                return {"name": h, "reachable": True, "checked": t, "last_ok": t, "ts": now, "packages": _ssh_parse(out, names)}
        except Exception as e:                               # one host's failure never drops the others' cards
            print(f"versions: ssh {h}: {e}", file=sys.stderr)
        pk = old.get("packages") if isinstance(old.get("packages"), dict) else {}
        e = {"name": h, "reachable": False, "checked": t, "ts": now, "packages": dict(pk)}
        if old.get("last_ok"):
            e["last_ok"] = old["last_ok"]
        return e
    cur = {h: prev[h] for h in hosts if h in prev and h not in due}
    if due:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(due)) as ex:
            for e in ex.map(probe, due):
                cur[e["name"]] = e
        SSH_OUT.parent.mkdir(parents=True, exist_ok=True)
        tmp = SSH_OUT.with_suffix(".tmp"); json.dump(cur, open(tmp, "w", encoding="utf-8")); os.replace(tmp, SSH_OUT)
    return [{**{k: v for k, v in cur[h].items() if k != "ts"}, "name": h} for h in hosts]


def _local(iso: str) -> str:
    return dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(ZONE).strftime("%m-%d %H:%M %Z")


def machines_state() -> tuple[dict[str, str], dict[str, str]]:
    """(letter → CLI version, letter → "live" | "offline since …") from the session and machine state: a machine is online
    while its puller checks in (machine.json `online`, written by clients.py), the publisher always; a machine with no puller
    on record is offline since it was last seen."""
    machines: dict[str, str] = {}; state: dict[str, str] = {}
    for L in _fleet.letters():
        d = _fleet.read(L, "machine")
        if not d:
            continue
        machines[L] = _norm(d.get("claude", ""))
        if L == _pub():
            state[L] = "live"; continue
        on = d.get("online") if isinstance(d.get("online"), dict) else None
        if on and on.get("ok"):
            state[L] = "live"
        elif on and on.get("since"):
            state[L] = "offline since " + _local(str(on["since"]))
        else:                                                # no puller vouches for it: its last sign of life says since when
            try:
                state[L] = "offline since " + _local(d.get("checked", ""))
            except Exception:
                state[L] = "offline"
    return machines, state


def write(force: bool = False) -> dict:
    latest = latest_all(force)
    rows = []
    for pk in _cfg.get("machines_panel", "packages") or []:
        name = pk["name"]; inst_spec = str(pk.get("installed") or "")
        extra: dict = {}
        if inst_spec == "fleet":
            machines, state = machines_state()
            own = _installed_cmd(pk["self_cmd"]) if pk.get("self_cmd") else ""
            if own:
                machines[_pub()] = own; state[_pub()] = "live"          # this box: the binary itself, not its fleet file
            inst = min((v for v in machines.values() if v), key=_vt, default="")   # the fleet's oldest = the version the fleet is "on"
            extra = {"machines": machines, "machine_state": state}
        elif inst_spec.startswith("cmd:"):
            inst = _installed_cmd(inst_spec[4:])
        else:
            inst = ""
        if pk.get("machines"):
            extra["hosts"] = list(pk["machines"])
        i, l = _norm(inst), _norm(latest.get(name, ""))
        st = "unknown" if not i or not l else ("latest" if i == l else "update")
        rows.append({"name": name, "installed": i or "?", "latest": l or "?", "state": st, **extra})
    doc = {"checked": dt.datetime.now(ZONE).strftime("%Y-%m-%d %H:%M %Z"), "packages": rows}
    try:
        hosts = ssh_hosts_read(force)
    except Exception as e:                                   # a failed ssh read never stops the panel's other versions
        print(f"versions: ssh hosts: {e}", file=sys.stderr); hosts = []
    if hosts:
        doc["ssh_hosts"] = hosts
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp"); json.dump(doc, open(tmp, "w", encoding="utf-8"), indent=1); os.replace(tmp, OUT)
    return doc


if __name__ == "__main__":
    print(json.dumps(write(force="--force" in sys.argv)))
