"""Scenario test for the open items' text (tools/open_item_text.py) — fixture data, no live store, no network, no server socket.

Open items with a /mockup/<n> link in the description, in the next, in a stored step and in the ask; a closed item with a link (never printed); an item with two links and a repeated one
(each printed once, sorted by number, not by text); an item with no link. The listing prefixes each line with the item id and leaves the closed item out; --links prints only the
distinct links found in ANY string of an open item's JSON (wait basis, work, said, subject, ... held items too), matched loosely on purpose (a prefix match: `/mockup/120x` is `/mockup/120`,
which only keeps a page longer; case-insensitive; ASCII digits; `/mockup/019` is `/mockup/19`). It fails closed: a store that is no folder (--store, or the configured one) exits 2 with nothing
on stdout; an item file that cannot be parsed exits 3 with the count on stderr and the other items' links still printed; a store with nothing matching prints nothing and exits 0; the tool writes no file.

    tests/run-suite open_item_text        → exit 0 / 1"""
import hashlib, json, os, pathlib, re, subprocess, sys, time

SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="oittest-"); T = pathlib.Path(tmp)
sys.path.insert(0, STACK); sys.path.insert(0, os.path.join(STACK, "tools"))

toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"), ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"),
                 ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml, count=1); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off")
(T / "store/a").mkdir(parents=True)
(T / "empty").mkdir()

from stackshot.tools import next_report as NR
sid = lambda n: NR.shown(f"a{n}")          # the id as the tool prints it
now = time.time()
def item(i, status="open", description="- A thing, finished when it works", **meta):
    base = {"project": "projects/alpha", **meta}
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": description, "status": status,
                                                     "updated": now - 3600, "state_updated": now - 3600, "confirmed": now - 3600, "metadata": base}))
item(1, description="- Looks like https://sala.example/mockup/7 in the page\n- second line")                          # a link in the description
item(2, next="home-agent: check /mockup/12 before the release")                                                      # a link in next
item(3, needs=["decision"], ask="Decide: pick a layout /mockup/5 · Recommend: A · Stakes: none · By: no date")         # a link in the ask
item(4, next="home-agent: compare /mockup/30 and /mockup/9", steps=[{"text": "home-agent: compare /mockup/30 and /mockup/9", "status": "open"}, {"text": "home-agent: open /mockup/9 again", "status": "open"}])   # two links, one repeated
item(5, description="- Nothing to see here", next="home-agent: build it")                                              # no link
item(6, status="completed", description="- Done. Was at /mockup/99", next="", ask="/mockup/98")                       # closed: never printed
item(7, next="home-agent: see /mockup/12 and /mockup/120x and /mockups/3")                                          # the same link as a2; `/mockup/120x` is deliberately read as `/mockup/120` (a prefix match: it can only keep a page longer, never drop one in use); `/mockups/3` is no link

fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
def digest(): return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((T / "store").glob("*/*.json"))}
d0 = digest()
def run(*a):
    r = subprocess.run([sys.executable, *a], capture_output=True, text=True, env=dict(os.environ)); return r.returncode, r.stdout, r.stderr
TOOL = os.path.join(STACK, "stackshot", "tools", "open_item_text.py")

rc, out, err = run(TOOL, "--store", str(T / "store"))
lines = out.splitlines()
check("the listing exits 0 with an id-prefixed line per line of text", rc == 0 and all(re.match(r"board#\d+: \S", ln) for ln in lines) and len(lines) > 0, (rc, out, err[-300:]))
check("a link in the description is printed under its item", any(ln.startswith(sid(1) + ": ") and "/mockup/7 in the page" in ln for ln in lines), lines)
check("a second description line is printed too", sid(1) + ": - second line" in lines, lines)
check("a link in next is printed", any(ln.startswith(sid(2) + ": ") and "/mockup/12" in ln for ln in lines), lines)
check("a link in the ask is printed", any(ln.startswith(sid(3) + ": ") and "/mockup/5 " in ln for ln in lines), lines)
check("a step text repeated in next is printed once", sum(sid(4) + ": home-agent: compare /mockup/30 and /mockup/9" == ln for ln in lines) == 1, lines)
check("an item with no link still lists its text", sid(5) + ": home-agent: build it" in lines, lines)
check("the closed item prints nothing", not any(sid(6) in ln or "/mockup/99" in ln or "/mockup/98" in ln for ln in lines), lines)

rc, out, err = run(TOOL, "--links", "--store", str(T / "store"))
check("--links: each distinct link once, sorted by number, nothing else; closed item's links absent",
      rc == 0 and out.splitlines() == ["/mockup/5", "/mockup/7", "/mockup/9", "/mockup/12", "/mockup/30", "/mockup/120"], (rc, out, err[-300:]))

rc, out, _ = run(TOOL, "--links", "--store", str(T / "empty"))
check("a store with nothing: no output, exit 0 (--links)", rc == 0 and out == "", (rc, out))
rc, out, _ = run(TOOL, "--store", str(T / "empty"))
check("a store with nothing: no output, exit 0 (listing)", rc == 0 and out == "", (rc, out))
rc, out, err = run(TOOL, "--store", str(T / "no-such"))
check("a --store that is no folder: exit 2", rc == 2 and out == "", (rc, out, err))
rc, out, _ = run(TOOL, "--links")
check("with no --store it reads [paths] store of the config (the fixture's, holding the same items)", rc == 0 and out.splitlines()[:2] == ["/mockup/5", "/mockup/7"], (rc, out))
# ---- the fail-closed cases: each in a store of its own (raw JSON, so a field can hold any shape)
def put(store, i, **fields):
    d = T / store / "a"; d.mkdir(parents=True, exist_ok=True)
    (d / f"{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item a{i}", "description": "- x", "status": "open", "metadata": {"project": "projects/alpha"}, **fields}))
def links_of(store, *extra):
    rc, out, err = run(TOOL, "--links", "--store", str(T / store), *extra); return rc, out.splitlines(), err

put("w", 1, metadata={"project": "projects/alpha", "wait_basis": {"text": "waits on /mockup/41 review"}})
put("w", 2, metadata={"project": "projects/alpha", "work": [{"text": "built /mockup/42"}, {"text": "none"}]})
put("w", 3, metadata={"project": "projects/alpha", "said": [{"msg": "see /mockup/43", "quote": "and /mockup/44"}]})
put("w", 4, subject="[home] about /mockup/45")
put("w", 5, metadata={"project": "projects/alpha", "hold": "wake", "wake": "2099-01-01", "options": [{"label": "A", "line": "/mockup/46"}]})   # a held item is open
put("w", 6, status="completed", subject="/mockup/97", metadata={"project": "projects/alpha", "work": [{"text": "/mockup/96"}]})                    # closed: never
rc, got, err = links_of("w")
check("--links finds a link only in wait_basis, work[], said[] (msg and quote), subject, and a held item's options",
      rc == 0 and got == [f"/mockup/{n}" for n in (41, 42, 43, 44, 45, 46)], (rc, got, err))

put("p", 1, description="- see /mockup/50.\n- or (/mockup/51) or /mockup/52?x=1 or /mockup/53#top or https://sala.example.com/mockup/54/view")
put("p", 2, description="- fullwidth /mockup/７８ and /mockup/٧ are no link")
put("p", 3, description="- /mockup/019 and /mockup/19 and /mockup/0019, upper /Mockup/60 and /MOCKUP/61 and /mockup/0 and /mockup/00")
rc, got, err = links_of("p")
check("a link before . ) ?x # or inside a URL with a host is found; fullwidth and arabic-indic digits are not; leading zeros fold; case is ignored; output is lowercase",
      rc == 0 and got == ["/mockup/0", "/mockup/19"] + [f"/mockup/{n}" for n in (50, 51, 52, 53, 54, 60, 61)], (rc, got, err))

put("o", 1, metadata=None)
put("o", 2, description=["a", "/mockup/70"], metadata={"project": "projects/alpha", "steps": "not a list", "next": 5, "ask": {"x": "/mockup/71"}})
put("o", 3, description=None, metadata={"project": "projects/alpha", "steps": [None, "x", {"text": None}, {"text": "/mockup/72"}]})
rc, got, err = links_of("o")
check("--links with metadata null, a non-string description, steps not a list, odd step entries: no crash, links still found",
      rc == 0 and got == ["/mockup/70", "/mockup/71", "/mockup/72"], (rc, got, err[-300:]))
rc, out, err = run(TOOL, "--store", str(T / "o"))
check("the listing copes with the same odd shapes", rc == 0 and "Traceback" not in err, (rc, out, err[-300:]))

# the configured store is missing: exit 2, one stderr line, empty stdout
bad_toml = (T / "stackshot.toml").read_text(encoding="utf-8").replace(f'store = "{tmp}/store"', f'store = "{tmp}/no-such-store"'); assert "no-such-store" in bad_toml
(T / "bad.toml").write_text(bad_toml, encoding="utf-8")
r = subprocess.run([sys.executable, TOOL, "--links"], capture_output=True, text=True, env={**os.environ, "STACKSHOT_CONFIG": f"{tmp}/bad.toml"})
check("a configured store that is missing: exit 2, nothing on stdout, one line on stderr", r.returncode == 2 and r.stdout == "" and len(r.stderr.strip().splitlines()) == 1, (r.returncode, r.stdout, r.stderr))
(T / "afile").write_text("x")
rc, out, err = run(TOOL, "--links", "--store", str(T / "afile"))
check("a --store that is a file, not a folder: exit 2, empty stdout", rc == 2 and out == "", (rc, out, err))

# unparseable item files: exit 3, the count on stderr, the other items' links still printed
put("u", 1, description="- /mockup/80")
(T / "u/a/2.json").write_text("{ not json")
(T / "u/a/3.json").write_text("[1, 2]")                         # parses, but is no item
(T / "u/a/notes.json").write_text("{ not json")                  # not an item file name: ignored as everywhere else
rc, got, err = links_of("u")
check("unparseable item files: exit 3, the count on stderr, the readable items' links still printed",
      rc == 3 and got == ["/mockup/80"] and err.strip().startswith("2 item file(s)"), (rc, got, err))
rc, out, err = run(TOOL, "--store", str(T / "u"))
check("...also in the listing mode", rc == 3 and f"{sid(1)}: - /mockup/80" in out and "2 item file(s)" in err, (rc, out, err))
if os.geteuid() != 0:
    put("v", 1, description="- /mockup/81"); (T / "v/b").mkdir(); (T / "v/b/1.json").write_text("{}"); os.chmod(T / "v/b", 0)
    try: rc, got, err = links_of("v")
    finally: os.chmod(T / "v/b", 0o755)
    check("a folder of the store that cannot be listed: exit 3, the other links printed", rc == 3 and got == ["/mockup/81"], (rc, got, err))

check("…and nothing was written by any of it", digest() == d0, None)

print(("ok" if not fails else "FAILED") + f": open_item_text scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
