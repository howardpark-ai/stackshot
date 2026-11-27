"""Scenario test for portal-sync.sh: what it asks the portal for, what it prints, and that its API token is never an argument of a program.
The script is run from a copy in a temp folder, beside stand-ins for the config reader and the catalog build; curl is a stand-in that records what it
is given. HOME is a temp folder and nothing leaves the machine.

    tests/run-suite portal_sync        → exit 0 / 1"""
import json, os, pathlib, shutil, subprocess, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch

T = pathlib.Path(_scratch.mkdtemp(prefix="portalsync-"))
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[-1800:]}" if got is not None else ""), flush=True)

TOKEN = "t0ken-" + "d4c3b2a1" * 5
HEADER = f"Authorization: Bearer {TOKEN}\n"
URL = "https://api.cloudflare.com/client/v4/accounts/acct1/access/ai-controls/mcp/servers/{}/sync"

CK = T / "checkout"; BIN = T / "bin"; HOME = T / "home"; LOG = T / "calls.jsonl"; TMP = T / "tmp"
for d in (CK / "stackshot/core", CK / "stackshot/fleet", BIN, HOME, TMP): d.mkdir(parents=True)
shutil.copy2(os.path.join(STACK, "portal-sync.sh"), CK / "portal-sync.sh")
(CK / "stackshot/core/config.py").write_text('''import os, sys
print({("get", "portal.account_id"): "acct1", ("get", "portal.server_id"): "main-server", ("path", "portal.token_file"): os.environ["FAKE_TOKEN_FILE"]}[tuple(sys.argv[1:3])])
''')
(CK / "stackshot/fleet/connectors.py").write_text('''import os, sys
print("catalog", *sys.argv[1:])
sys.exit(int(os.environ.get("FAKE_BUILD_RC", "0")))
''')
(BIN / "curl").write_text(f'''#!{sys.executable} -IS
import json, os, sys
args = sys.argv[1:]
rc = int(os.environ.get("FAKE_CURL_RC", "0"))
with open({str(LOG)!r}, "a") as f: f.write(json.dumps({{"args": args, "stdin": sys.stdin.read()}}) + "\\n")
if rc: sys.exit(rc)
with open(args[args.index("-o") + 1], "w") as f: f.write('{{"result": {{"tools": [1, 2]}}}}')
sys.stdout.write("200")
''')
(BIN / "curl").chmod(0o755)
os.symlink(sys.executable, BIN / "python3")
for name in ("bash", "cat", "dirname", "mktemp", "rm"):
    real = shutil.which(name); assert real, name
    os.symlink(real, BIN / name)
(T / "token").write_text(TOKEN + "\n"); (T / "other-token").write_text("another-" + "z" * 30 + "\n")


def sync(*ids, **env):
    LOG.write_text("")
    e = {"HOME": str(HOME), "PATH": str(BIN), "TMPDIR": str(TMP), "FAKE_TOKEN_FILE": str(T / "token"), **env}
    r = subprocess.run([str(BIN / "bash"), str(CK / "portal-sync.sh"), *ids], env=e, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout + r.stderr, [json.loads(x) for x in LOG.read_text().splitlines()]


rc, out, calls = sync()
check("the configured server is synced and the answer reported", rc == 0 and "portal-sync: main-server http=200 tools=2" in out and "catalog build" in out, (rc, out))
check("one POST to the portal with a time limit of 60 s", len(calls) == 1 and calls[0]["args"][-1] == URL.format("main-server")
      and calls[0]["args"][calls[0]["args"].index("-X") + 1] == "POST" and calls[0]["args"][calls[0]["args"].index("-m") + 1] == "60", calls)
check("the token is no argument of curl: the header comes on its stdin", calls and not [a for a in calls[0]["args"] if TOKEN in a or "Bearer" in a]
      and calls[0]["args"][calls[0]["args"].index("-H") + 1] == "@-" and calls[0]["stdin"] == HEADER, calls)
check("the token is not printed", TOKEN not in out, out)
check("the file of the answer is removed", not list(TMP.iterdir()), list(TMP.iterdir()))

rc, out, calls = sync("one", "two")
check("each server named gets its own call, each with the header", rc == 0 and [c["args"][-1] for c in calls] == [URL.format("one"), URL.format("two")]
      and all(c["stdin"] == HEADER for c in calls) and "portal-sync: two http=200" in out, (rc, out, calls))

rc, out, calls = sync(CF_API_TOKEN_FILE=str(T / "other-token"))
check("CF_API_TOKEN_FILE names another token file", calls and calls[0]["stdin"] == "Authorization: Bearer another-" + "z" * 30 + "\n", calls)

rc, out, calls = sync(FAKE_CURL_RC="7")
check("a call that fails is reported as 000 and the catalog is still built", rc == 0 and "portal-sync: main-server http=000 tools=?" in out and "catalog build" in out, (rc, out))

rc, out, calls = sync(FAKE_BUILD_RC="3")
check("a catalog build that fails is said and does not fail the sync", rc == 0 and "connectors.py build exited 3" in out, (rc, out))

print(("ok" if not fails else "FAILED") + f": portal sync scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else ""), flush=True)
sys.exit(1 if fails else 0)
