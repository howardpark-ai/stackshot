#!/usr/bin/env python3
"""tests/home_brain_probe.py: the live probe of the home brain's untested points, run by hand on a throwaway brain. NOT a suite (no `_scenario` name, CI never runs it:
point 1 builds a gbrain from a source tree on a remote test host). One command prints PASS or FAIL for each point, with the numbers:

    python3 tests/home_brain_probe.py --verify <verify-gbrain's verify.py> --gbrain-source <gbrain tree> --gbrain-ref <branch|tag|commit> [--runner '<test runner prefix>']

  1. A gbrain served as `gbrain serve --http` with a token minted `--scopes read,write` lists no admin tool and no host-only tool (the tool count is
     printed, with the count the default admin-rights token gets). Runs the verify-gbrain skill's harness (its --verify path), which builds the brain from the source tree on a remote test host and takes it down; the journey is
     tests/home_brain_probe_journey.py. What it covers: gbrain's own tools/list for that token. What it does not: the front door in front of it (see
     docs/front-door.md, *The home brain probe*).
  2. NOT TESTABLE today: a front door serves at most one brain, and a brain tool takes no `board`, so there is no per-board routing to probe.
  3. The board's publisher commits a page file under pages/ with the signed-in person as git author and the board's bot as committer, pushed to a
     local bare repository. `publish.publish_pages()` is driven directly, [publish] pages on in the config the probe writes. Runs where --runner says
     (git and the stackshot code only, no gbrain), or in this process with none.

Exit 0 when each testable point is PASS; 1 when one is FAIL; 2 when a point could not be run (a harness that failed to start is no verdict).
Everything the probe makes is removed when it ends (the harness's scratch, this probe's folder from tests/_scratch.py)."""
import argparse, os, pathlib, re, shlex, subprocess, sys

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
NOT_TESTABLE = "NOT TESTABLE: a front door serves at most one brain (frontdoor_config.py:234-235), brain tools take no board"
SKILL_NOTE = "the harness's own verdict line"


def point1(source: str, ref: str, verify: str) -> tuple[str, str]:
    """("PASS"|"FAIL"|"NO VERDICT", the numbers). The harness exits 0 PASS, 1 FAIL, 2 no verdict; its output holds the journey's PROBE line."""
    cmd = [os.path.expanduser(verify), "--source", os.path.expanduser(source), *(["--ref", ref] if ref else []), os.path.join(SCR, "home_brain_probe_journey.py")]
    r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=1500)
    out = r.stdout + r.stderr
    line = next((x for x in out.splitlines() if x.startswith("PROBE read,write")), "")
    fails = [x for x in out.splitlines() if x.startswith("FAIL")]
    tail = fails[0][:300] if fails else (out.strip().splitlines() or [""])[-1][:300]
    if r.returncode == 2 or not line and r.returncode == 0:
        return "NO VERDICT", f"{line or tail} ({SKILL_NOTE}: exit {r.returncode})"
    return ("PASS" if r.returncode == 0 else "FAIL"), (line.removeprefix("PROBE ") if line else "") + ("" if r.returncode == 0 else f"; {tail}")


def point3_here() -> tuple[str, str]:
    """The publisher against a bare repository, in this process. ("PASS"|"FAIL", numbers)"""
    import _scratch, _instance
    tmp = _scratch.mkdtemp(prefix="homeprobe-"); T = pathlib.Path(tmp)
    toml = _instance.apply(_instance.base_toml())
    toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1)
    toml, n = re.subn(r'(?m)^pages = false\b', 'pages = true', toml, count=1); assert n == 1, "no `pages = false` under [publish] in the example config"
    for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("fleet_names", f"{tmp}/names.tsv"),
                     ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
        toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
    (T / "stackshot.toml").write_text(toml, encoding="utf-8")
    os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off")
    for k in ("STACKSHOT_FLEET_DIR", "STACKSHOT_URL", "BOARD_MCP_AUTH"): os.environ.pop(k, None)
    for d in ("state", "secrets"): (T / d).mkdir(parents=True)
    (T / "gitconfig").write_text("[user]\n\tuseConfigOnly = true\n", encoding="utf-8")        # the host's own git identity never takes part
    for k in [k for k in os.environ if k.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_"))]: os.environ.pop(k)
    os.environ.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(T / "gitconfig"))
    sys.path.insert(0, STACK)
    import logging; logging.disable(logging.WARNING)
    from stackshot.web import publish as P

    def git(cwd, *a):
        r = subprocess.run(["git", "-C", str(cwd), *a], capture_output=True, text=True)
        assert r.returncode == 0, (a, r.stderr)
        return r.stdout.strip()
    seed_id = ("-c", "user.name=Seed", "-c", "user.email=seed@x")
    origin, store = T / "origin.git", T / "store"
    git(T, "init", "-q", "--bare", "-b", "main", str(origin))
    git(T, "clone", "-q", str(origin), str(store))
    (store / "board.md").write_text("board\n"); git(store, "add", "-A"); git(store, *seed_id, "commit", "-q", "-m", "first")
    git(store, "branch", "-M", "main"); git(store, "push", "-q", "-u", "origin", "main")
    P.REPO = store; P._SERVING = True
    BOT, BOT_MAIL = "Board Bot", "bot@board.example"
    os.environ.update(GIT_COMMITTER_NAME=BOT, GIT_COMMITTER_EMAIL=BOT_MAIL)                  # what the server's process has: a committer, no author
    fails, ran = [], []

    def check(name, cond, got=None):
        ran.append(name)
        if not cond: fails.append(f"{name}: {str(got)[:300]}")
    people = (("Ada Example", "ada@example.org", "pages/ada-note.md", "# ada\n"), ("Bo Example", "", "pages/sub/bo-note.md", "# bo\n"))
    base = int(git(store, "rev-list", "--count", "HEAD"))
    for i, (name, mail, rel, text) in enumerate(people, 1):
        p = store / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
        got = P.publish_pages([rel.removeprefix("pages/")], name, mail)
        fmt = git(store, "log", "-1", "--format=%an|%ae|%cn|%ce|%s")
        an, ae, cn, ce, subj = fmt.split("|", 4)
        check(f"{name}: publish_pages returned True and made one commit", got is True and int(git(store, "rev-list", "--count", "HEAD")) == base + i, got)
        check(f"{name}: the commit's author is the person", an == name and (ae == mail if mail else bool(ae)), fmt)
        check(f"{name}: the commit's committer is the board's bot", (cn, ce) == (BOT, BOT_MAIL), fmt)
        check(f"{name}: the commit holds the page file under pages/ and nothing else", git(store, "show", "--name-only", "--format=", "HEAD").splitlines() == [rel], rel)
        check(f"{name}: it is on the bare repository", git(origin, "rev-parse", "main") == git(store, "rev-parse", "HEAD") and git(origin, "show", f"main:{rel}") == text.strip(), rel)
    head = git(store, "rev-parse", "HEAD")
    check("an unchanged page makes no commit (False)", P.publish_pages(["ada-note.md"], "Ada Example", "ada@example.org") is False and git(store, "rev-parse", "HEAD") == head)
    try: P.publish_pages(["../board.md"], "Ada Example"); out = "returned"
    except P.CommitFailed as e: out = "refused"
    check("a path outside pages/ is refused and nothing is committed", out == "refused" and git(store, "rev-parse", "HEAD") == head, out)
    authors = git(store, "log", "--format=%an", f"-{len(people)}").splitlines()
    nums = f"{len(people)} page commits pushed to a bare repository, authors {', '.join(reversed(authors))}, committer {BOT}; {len(ran)} checks"
    return ("FAIL", f"{nums}; failed: {'; '.join(fails)}") if fails else ("PASS", nums)


def point3_run(runner: list[str]) -> tuple[str, str]:
    """Point 3 through `runner` (a command prefix that runs what follows in a copy of this tree on the test host and gives back its output; none: this process)."""
    inner = ["uv", "run", "--locked", "--project", ".", "--only-group", "tests", "python", os.path.join("tests", "home_brain_probe.py"), "--point", "3", "--here"]
    r = subprocess.run([*runner, *inner], capture_output=True, text=True, cwd=STACK, stdin=subprocess.DEVNULL, timeout=1900)
    out = r.stdout + r.stderr
    line = next((x for x in out.splitlines() if x.startswith(("PASS point 3", "FAIL point 3"))), None)
    if line:
        v, _, rest = line.partition(" point 3 ")
        return v, rest
    return "NO VERDICT", (out.strip().splitlines() or [""])[-1][:300]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--gbrain-source", help="a gbrain checkout or worktree (only read), for point 1")
    ap.add_argument("--gbrain-ref", default="", help="the branch, tag or commit of it to send (default: its working tree)")
    ap.add_argument("--verify", help="the verify-gbrain skill's verify.py (point 1)")
    ap.add_argument("--runner", default="", help="a command prefix that runs point 3 on the test host, e.g. a remote runner's name and its flags, ending in `--`")
    ap.add_argument("--point", choices=("1", "3"), help="run one point only")
    ap.add_argument("--here", action="store_true", help="point 3 in this process (what dio-run runs)")
    a = ap.parse_args()
    if a.point == "3" and a.here:
        sys.path.insert(0, SCR)
        v, nums = point3_here(); print(f"{v} point 3 {nums}"); return 0 if v == "PASS" else 1
    results = {}
    if a.point in (None, "1"):
        if not (a.gbrain_source and a.verify): ap.error("--gbrain-source and --verify are required for point 1")
        results[1] = point1(a.gbrain_source, a.gbrain_ref, a.verify)
    if a.point is None: results[2] = ("NOT TESTABLE", NOT_TESTABLE.removeprefix("NOT TESTABLE: "))
    if a.point in (None, "3"): results[3] = point3_run(shlex.split(a.runner))
    for n in sorted(results):
        v, nums = results[n]
        print(NOT_TESTABLE if n == 2 else f"{v} point {n}: {nums}")
    verdicts = [v for v, _ in results.values()]
    return 2 if "NO VERDICT" in verdicts else 1 if "FAIL" in verdicts else 0


if __name__ == "__main__":
    sys.exit(main())
