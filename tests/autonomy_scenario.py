"""Scenario test for the autonomy profile (stackshot/core/autonomy.py), its read tool (web/tools/autonomy.py) and its `stackshot doctor` lines — made-up config and profile files,
a fresh process for each read, no store, no network.

Covers:
  * the fallback: an absent file, a file that is not TOML, a `person` that is no table, a missing person, a missing kind, a word that is no level (a typo, a number), an unknown kind and
    an empty kind all read `hand-on`, and nothing raises;
  * a written level is read as written, for the member's name or an alias in any case;
  * the file is read by its stamp: an edit is seen by the same process at its next call, with no restart;
  * the file's place: `[paths] autonomy`, else `autonomy.toml` in `[paths] repo`;
  * the kinds and levels of the design, and the example profile in docs/ naming each kind with a level word;
  * the read-back through the `autonomy` tool: one kind gives `<kind>: <level>`, none gives the whole table, an unknown kind says hand-on;
  * doctor names a member with no table, a kind with no level, a word that is no level, an unreadable file, and says nothing is wrong for a whole profile; it never changes the file.

    tests/run-suite autonomy      -> exit 0 / 1"""
import json, os, pathlib, re, subprocess, sys, tomllib

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="autonomy-"); T = pathlib.Path(tmp)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:700]}" if got is not None else ""))

BASE = _instance.base_toml()
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("fleet_names", f"{tmp}/names.tsv"), ("state", f"{tmp}/state"),
                 ("secrets", f"{tmp}/secrets"), ("session_links", f"{tmp}/sala"), ("project_touch", f"{tmp}/touch")):
    BASE, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', BASE); assert n == 1, key
BASE, n = re.subn(r'(?m)^base_url = "[^"]*"', 'base_url = "http://127.0.0.1:9"', BASE); assert n == 1
(T / "secrets").mkdir(); (T / "secrets/oauth.env").write_text("", encoding="utf-8")
PROFILE = T / "profile.toml"
KINDS = ["release", "release-migrating", "design-choice", "new-notice", "spend", "message-person", "email", "connector-write", "merge", "delete", "retire", "revive", "fleet-op", "public-repo"]


def config(label, key=True, members=("Pat",)):
    text = BASE
    text, n = re.subn(r'(?m)^autonomy = "[^"]*".*$', f'autonomy = "{PROFILE}"' if key else "", text); assert n == 1
    for m in members:
        text += f'\n[[members]]\nname = "{m}"\naliases = ["{m[:2]}"]\nemails = ["{m.lower()}@example.com"]\n'
    p = T / f"{label}.toml"; p.write_text(text, encoding="utf-8"); return p


def env_for(path):
    env = {k: v for k, v in os.environ.items() if not k.startswith("STACKSHOT_") and k not in ("BOARD_MCP_CONFIG", "BOARD_MCP_AUTH")}
    env.update(STACKSHOT_CONFIG=str(path), HOME=str(T / "home"), PYTHONDONTWRITEBYTECODE="1", STACKSHOT_PROC_NET=str(T / "procnet-none"))
    return env


def run(path, code, extra=None):
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**env_for(path), **(extra or {})}, cwd=STACK, timeout=300)


READ = r"""
import json
from stackshot.core import autonomy as a
probes = [("Pat", "release"), ("pat", "release"), ("Pa", "release"), ("Pat", "design-choice"), ("Pat", "spend"), ("Pat", "merge"), ("Pat", "fleet-op"), ("Pat", "bogus"), ("Pat", ""), ("Nobody", "release"), ("", "release"), (None, None)]
print(json.dumps({"levels": [a.level(p, k) for p, k in probes], "table": a.table("Pat"), "path": str(a.path())}))
"""
cfg = config("main")


# ---- 1. the fallback: nothing raises, everything reads hand-on
def levels(text):
    if text is None:
        PROFILE.unlink(missing_ok=True)
    else:
        PROFILE.write_bytes(text.encode("utf-8"))
    r = run(cfg, READ)
    return (json.loads(r.stdout), r.stderr) if r.returncode == 0 else (None, r.stderr[-600:])


for label, text in (("absent file", None), ("a file that is not TOML", "version = [\n[person"), ("person that is no table", 'person = "x"\n'), ("an empty file", ""),
                    ("a binary file", "\x00\x01\x02")):
    got, err = levels(text)
    check(f"fallback: {label} reads hand-on and raises nothing", got is not None and set(got["levels"]) == {"hand-on"} and set(got["table"].values()) == {"hand-on"}, (got, err))

# ---- 2. a written level is read as written; every gap beside it is hand-on
got, err = levels('version = 1\n[person.Pat]\nrelease = "auto"\nmerge = "when-told"\nspend = "yes"\nfleet-op = 3\nbogus = "auto"\n[person.Other]\ndesign-choice = "auto"\n')
check("a written level is read, by name, lower case and alias", got and got["levels"][:3] == ["auto", "auto", "auto"], (got, err))
check("a kind with no key reads hand-on", got and got["levels"][3] == "hand-on", got)
check("a word that is no level and a value that is no text read hand-on", got and got["levels"][4] == "hand-on" and got["levels"][6] == "hand-on", got)
check("another written level (merge) is read", got and got["levels"][5] == "when-told", got)
check("an unknown kind, even one written in the file, an empty kind and no kind read hand-on", got and got["levels"][7:9] == ["hand-on", "hand-on"] and got["levels"][11] == "hand-on", got)
check("a missing person and an empty one read hand-on, and another person's level is not Pat's", got and got["levels"][9:11] == ["hand-on", "hand-on"], got)
check("table() has the fourteen kinds, each a level word", got and list(got["table"]) == KINDS and got["table"]["release"] == "auto" and got["table"]["merge"] == "when-told"
      and set(got["table"].values()) <= {"auto", "when-told", "ask-first", "hand-on"}, got)

# ---- 3. read by the file's stamp, in one process
CHANGE = r"""
import json, pathlib, time
from stackshot.core import autonomy as a
p = pathlib.Path(a.path())
out = []
p.write_text('[person.Pat]\nrelease = "auto"\n'); out.append(a.level("Pat", "release")); time.sleep(0.5)
out.append(a.level("Pat", "release"))
p.write_text('[person.Pat]\nrelease = "ask-first"\n'); out.append(a.level("Pat", "release")); time.sleep(0.5)
p.write_text('[person.Pat]\nrelease = "when-told"\n'); out.append(a.level("Pat", "release")); out.append(a.level("Pat", "release"))
p.unlink(); out.append(a.level("Pat", "release"))
print(json.dumps(out))
"""
r = run(cfg, CHANGE)
check("the file is read by its stamp: each edit is seen at the next call, a removal reads hand-on", r.returncode == 0 and json.loads(r.stdout) == ["auto", "auto", "ask-first", "when-told", "when-told", "hand-on"], (r.stdout, r.stderr[-400:]))

# ---- 4. the file's place
r = run(config("nokey", key=False), "from stackshot.core import autonomy as a; print(a.path())")
check("with no [paths] autonomy the file is autonomy.toml in paths.repo", r.returncode == 0 and r.stdout.strip() == f"{tmp}/autonomy.toml", (r.stdout, r.stderr[-300:]))
check("the example config names the key, and its path is the default's", re.search(r'(?m)^autonomy = "~/stackshot-data/autonomy\.toml"', pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8")) is not None)

# ---- 5. the kinds, the levels and the example profile
r = run(cfg, "import json; from stackshot.core import autonomy as a; print(json.dumps({'kinds': a.KINDS, 'levels': a.LEVELS}))")
d = json.loads(r.stdout) if r.returncode == 0 else {"kinds": [], "levels": []}
check("fourteen kinds, each with a one-line meaning, in the design's order", [k for k, _ in d["kinds"]] == KINDS and all(m and "\n" not in m for _, m in d["kinds"]), (d["kinds"], r.stderr[-300:]))
check("four level words, least to most careful", d["levels"] == ["auto", "when-told", "ask-first", "hand-on"], d["levels"])
ex = tomllib.loads(pathlib.Path(STACK, "docs", "autonomy.example.toml").read_text(encoding="utf-8"))
row = ex["person"]["owner"]
check("the example profile has a table whose keys are exactly the kinds, each a level word", ex.get("version") == 1 and list(row) == KINDS and set(row.values()) <= set(d["levels"]), row)
check("the example profile has the design's defaults", row["release"] == "auto" and row["release-migrating"] == "ask-first" and row["message-person"] == "hand-on"
      and row["connector-write"] == "when-told" and row["public-repo"] == "hand-on", row)

# ---- 6. read-back through the tool
TOOL = r"""
import asyncio, json, logging
logging.disable(logging.WARNING)
from stackshot.web import server
from stackshot.web.auth import oauth
oauth._who = lambda: 'pat@example.com'      # the call has no request: the signed-in member is made up
async def call(**kw):
    r = await server.mcp.call_tool("autonomy", kw)
    return r.content[0].text
async def main():
    got = [await call(person="Pat", kind="release"), await call(person="pa", kind="spend"), await call(person="Pat", kind="bogus"), await call(person="Nobody", kind="release"), await call(person="Pat")]
    return {"out": got, "names": sorted(t.name for t in await server.mcp.list_tools())}
print("RESULT " + json.dumps(asyncio.run(main())))
"""
PROFILE.write_text("[person.Pat]\n" + "\n".join(f'{k} = "{"auto" if i == 0 else "ask-first"}"' for i, k in enumerate(KINDS)) + "\n", encoding="utf-8")
r = run(cfg, TOOL, {"STACKSHOT_GOOGLE_CLIENT_ID": "test-client-id.apps.googleusercontent.com", "STACKSHOT_GOOGLE_CLIENT_SECRET": "test-secret"})
res = next((json.loads(ln[7:]) for ln in r.stdout.splitlines() if ln.startswith("RESULT ")), None)
out = res["out"] if res else None
check("tool: one kind reads back its written level", out and out[0] == "release: auto" and out[1] == "spend: ask-first", (out, r.stderr[-500:]))
check("tool: an unknown kind and an unknown person read hand-on", out and out[2].startswith("bogus: hand-on") and out[3] == "release: hand-on", out)
check("tool: no kind gives one line per kind, in order, with its level and meaning", out and [ln.split(":")[0] for ln in out[4].splitlines()] == KINDS
      and out[4].splitlines()[0].startswith("release: auto · ") and out[4].splitlines()[1].startswith("release-migrating: ask-first · "), out)
check("tool: `autonomy` is registered and no tool writes the profile", res and "autonomy" in res["names"] and not [n for n in res["names"] if n.startswith("autonomy") and n != "autonomy"], res and res["names"])


# ---- 7. doctor
def doctor(label, text, members=("Pat",)):
    if text is None:
        PROFILE.unlink(missing_ok=True)
    else:
        PROFILE.write_text(text, encoding="utf-8")
    before = PROFILE.read_bytes() if PROFILE.exists() else None
    r = subprocess.run([os.path.join(STACK, "bin", "stackshot"), "doctor", "--no-systemd"], capture_output=True, text=True, env=env_for(config(label, members=members)), cwd=STACK,
                       stdin=subprocess.DEVNULL, timeout=300)
    after = PROFILE.read_bytes() if PROFILE.exists() else None
    return [ln for ln in r.stdout.splitlines() if re.match(r"\s+\w+\s+autonomy: ", ln)], before == after, r.stdout


whole = "[person.Pat]\n" + "\n".join(f'{k} = "auto"' for k in KINDS) + "\n"
lines, same, out = doctor("d-whole", whole)
check("doctor: a whole profile says so, as ok", len(lines) == 1 and re.search(r"ok\s+autonomy: every member", lines[0]) is not None and same, (lines, out[-500:]))
lines, same, out = doctor("d-absent", None)
check("doctor: an absent file is one warning that says every action reads hand-on, and is not a missing",
      len(lines) == 1 and lines[0].lstrip().startswith("warn") and "does not exist" in lines[0] and "hand-on" in lines[0], (lines, out[-500:]))
lines, same, out = doctor("d-bad", "[person\nrelease =")
check("doctor: a file that is not TOML is named as one that cannot be read", len(lines) == 1 and "cannot be read" in lines[0] and lines[0].lstrip().startswith("warn"), lines)
lines, same, out = doctor("d-gaps", '[person.Pat]\nrelease = "sure"\nmerge = "auto"\nbogus = "auto"\n', members=("Pat", "Sam"))
joined = "\n".join(lines)
check("doctor: a member with no table is named", "member Sam has no [person.Sam] table" in joined, lines)
check("doctor: a kind with no level is named, a written one is not", "[person.Pat] has no level for spend" in joined and "no level for merge" not in joined, lines)
check("doctor: a word that is no level is named with the word", "[person.Pat] release = 'sure' is no level" in joined, lines)
check("doctor: a key that is no kind is named", "bogus is no kind of action" in joined, lines)
check("doctor: it fixes nothing (the file is the same after) and every line is a warning, not a missing", same and all(ln.lstrip().startswith("warn") for ln in lines), lines)

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
