#!/usr/bin/env python3
"""rename_page.py — move gbrain pages to new slugs, byte for byte (on the server box only: the gbrain CLI and the database are there).

gbrain has no rename verb (rulebook, *gbrain* section): a page is renamed by writing it under the new slug with
`aliases: [<old>]` and turning the old slug into a redirect stub. A project rename is stackshot's job, and
this is its page half. The board items' `project` keys and the anchors' keys are moved between the two phases:

    rename_page.py plan  OLD=NEW [OLD=NEW …]      print what would be written, write nothing
    rename_page.py copy  OLD=NEW [OLD=NEW …]      put each page (and every page under it) at its new slug and read it back
    rename_page.py stub  OLD=NEW [OLD=NEW …]      turn each old slug into a redirect stub — refused for a page that changed
                                                  since `copy` read it (run `copy` again)
                                                  and moves each page's project id (projects.py) to its new key
Options: --why "<one line for the stub's dated bullet>" · --parent SLUG (set `parent:` on the moved top page; a page nested only by `parent:`
         still needs an agents map or --no-agents-ok, the registry knows no sub-page by it) ·
         --no-agents-ok (a deliberate move to a project page with no agents map).

A page that lands as a top-level `type: project` page (no ancestor page of the registry, no `hub:` line; a `parent:` line makes no sub-page; not retired, done or moved) must list a front agent
on its `agents:` map, its -main agent: the board's items and notices of a project go to it. When the destination does not, `plan` and
`copy` print a WARN line and `stub` refuses (FAIL, exit 1, nothing changed): add the agents map with its -main agent on the destination
page (ask the keeper or the project's -main agent), then run `stub` again. This holds for a type change too: a page that was no project
at the old slug and is one at the new. A one-session page is left alone: its `display-name:` names a live sala session (or one that starts
with it) and no other project's name is that session's prefix. When it is (the ax case: `<other-project>-ax` on a page of its own), or the name line's session is not live, the page is
refused too, with a message that says so. A sub-page, a note and a destination that lists a front agent are not touched by it.

What changes in a moved page: frontmatter gains `aliases`; references to the moved slugs ([[wikilinks]] and the notes repo mirror
URLs) follow in the frontmatter, in the compiled truth and in the timeline's "Older entries:" pointer. Timeline bullets are
records and stay as written; their links keep working through the stubs. Pages over the connector's size limit and pages with
facts tables move the same way: the content is never retyped.
"""
import datetime, json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as _cfg  # noqa: E402  (stackshot.toml: paths.brain, gbrain.mirror_url, paths.state)
import brains as _brains  # noqa: E402  ([[brains]]: the brain that holds a slug, its copy and its gbrain home)
HOME = os.path.expanduser("~"); G = _cfg.gbrain_bin()      # [gbrain] bin: "gbrain" on PATH by default
BRAIN = str(_cfg.path("paths", "brain")); MIRROR = str(_cfg.get("gbrain", "mirror_url") or "").replace("{key}", "{slug}")
STATE = str(_cfg.state("rename"))
_m = re.match(r"https?://[^/]+/[^/]+/([^/]+)/", MIRROR)
BRAIN_REPO = _m.group(1) if _m else ""      # the notes repo's name in [gbrain] mirror_url: its blob and tree URLs follow a moved slug
MARK = "<!-- timeline -->"
FENCE = re.compile(r"(<!---? ?gbrain:(?:facts|takes):begin.*?gbrain:(?:facts|takes):end ?-?-->)", re.S)
ENV = {**os.environ, "PATH": (os.path.dirname(G) + os.pathsep if os.path.dirname(G) else "") + os.environ.get("PATH", "")}
PLAIN_MSG = ("the gbrain command line is not used with plain pages ([pages] flavor = \"plain\"): this instance keeps its pages as markdown files in "
             "paths.brain, so a page is moved or renamed by editing the files and committing; set [pages] flavor = \"gbrain\" and [gbrain] bin for a gbrain brain")

class PlainPages(RuntimeError):
    """A gbrain call asked for under plain pages: the message says what to do instead."""

def _slug_of(args):
    """The page a gbrain call is about: `put <slug> …`, or the `slug` of a `call <tool> '<json>'`; "" when it names none."""
    if len(args) > 1 and args[0] == "put": return str(args[1])
    if len(args) > 2 and args[0] == "call":
        try: return str((json.loads(args[2]) or {}).get("slug") or "")
        except Exception: return ""
    return ""

def gb(args, stdin=None, slug=None):
    """One gbrain CLI call, with GBRAIN_HOME of the brain that holds the slug ([[brains]]; the default brain keeps the environment as it is,
    unless [gbrain] home is set). A second brain is always written through gbrain, whatever [pages] flavor says for the default one."""
    slug = _slug_of(args) if slug is None else slug
    b = _brains.for_key(slug) if slug else _brains.default()
    if _cfg.page_flavor() != "gbrain" and b.default: raise PlainPages(PLAIN_MSG)
    env, why = _brains.prepare(slug, ENV, b)    # one read of the brain's secret_file decides the refusal and the environment: a copy without the parent's client secret
    if why: return 2, why                       # a second brain with no `home` (the CLI would run on the default brain's home: a read would return its page, a write land in it)
                                                # or with an unusable secret_file: neither runs
    r = subprocess.run([G, *args], input=stdin, capture_output=True, text=True, cwd=HOME, env=env, timeout=120)   # never inside a repo
    return r.returncode, _brains.redact((r.stdout or "") + (r.stderr or ""), env)

def _json(out):
    """The JSON object in gb()'s output, text around it ignored: stderr follows stdout there, and the CLI's upgrade notice
    ("UPGRADE_AVAILABLE …", "gbrain X -> Y available") lands after the object (every page read as unreadable)."""
    i = out.find("{")
    try: d = json.JSONDecoder().raw_decode(out[i:])[0] if i >= 0 else {}
    except Exception: d = {}
    return d if isinstance(d, dict) else {}

def get(slug):
    rc, out = gb(["call", "get_page", json.dumps({"slug": slug, "include_content": True, "content_only": True})])
    d = _json(out)
    return (d["content"], d["revision"]) if "content" in d and "revision" in d else (None, None)

def family(old):
    """The page and every page under it, from the mirror's file tree (slugs)."""
    b = _brains.for_key(old); base = BRAIN if b.default else str(b.path)    # the copy of the brain that holds the page
    out = [old]; d = os.path.join(base, old)
    for root, _dirs, files in os.walk(d) if os.path.isdir(d) else []:
        for f in sorted(files):
            if f.endswith(".md"): out.append(os.path.relpath(os.path.join(root, f), base)[:-3].replace(os.sep, "/"))
    return out

def relink(text, pairs, plain=False):
    """Old slugs → new in [[wikilinks]] and the notes repo mirror URLs; `plain` also in bare mentions (frontmatter values), never
    inside another repo's path (<ops folder>/projects/…)."""
    for old, new in sorted(pairs, key=lambda p: -len(p[0])):
        o = re.escape(old)
        text = re.sub(r"(\[\[)" + o + r"(?=[\]/|#])", lambda m: m.group(1) + new, text)
        if BRAIN_REPO: text = re.sub(r"(" + re.escape(BRAIN_REPO) + r"/(?:blob|tree)/main/)" + o + r"(?=[./)#\s]|$)", lambda m: m.group(1) + new, text)
        if plain: text = re.sub(r"(?<![\w/-])" + o + r"(?![\w-])", new, text)
    return text

def split_fm(content):
    assert content.startswith("---\n"), "no frontmatter"
    j = content.index("\n---\n", 4)
    return content[4:j], content[j + 5:]

def transform(content, old, new, pairs, parent=None):
    fm, body = split_fm(content)
    fm = relink(fm, pairs, plain=True)
    if re.search(r"(?m)^aliases:", fm):
        fm = re.sub(r"(?m)^aliases:[ \t]*(\[\s*\])?[ \t]*$", "aliases:\n  - " + old, fm, count=1) if re.search(r"(?m)^aliases:[ \t]*(\[\s*\])?[ \t]*$", fm) else fm + "\n  - " + old if fm.rstrip().split("\n")[-1].startswith("  - ") and "aliases" in fm.rsplit("\n\n", 1)[-1] else fm
        assert old in fm, f"could not add the alias to {new}: aliases key in an unexpected shape"
    else: fm = fm.rstrip("\n") + "\naliases:\n  - " + old
    if parent:
        fm = re.sub(r"(?m)^parent:.*$", "parent: " + parent, fm) if re.search(r"(?m)^parent:", fm) else fm.rstrip("\n") + "\nparent: " + parent
    if MARK in body:
        i = body.rindex(MARK); head, tail = body[:i], body[i:]
        tail = "\n".join(relink(l, pairs) if l.startswith("Older entries:") else l for l in tail.split("\n"))
    else:                                   # an archive page: only what stands above its first dated bullet
        m = re.search(r"(?m)^- \*\*\d{4}-\d\d-\d\d\*\*", body); i = m.start() if m else len(body); head, tail = body[:i], body[i:]
    parts = FENCE.split(head)                # a facts or takes fence moves byte for byte: gbrain indexes its rows from it
    head = "".join(p if FENCE.fullmatch(p) else relink(p, pairs) for p in parts)
    return "---\n" + fm.rstrip("\n") + "\n---\n" + head + tail

def _link(label, slug):
    """The stub's link to the new page: the mirror of the brain that holds the slug. A second brain with no mirror_url gets no link and the
    stub says so, never the default brain's mirror (that page is not there)."""
    b = _brains.for_key(slug)
    if b.default: return "[" + label + " on GitHub](" + MIRROR.format(slug=slug) + ")"
    if b.mirror_url: return "[" + label + " on GitHub](" + _brains.mirror(slug) + ")"
    return label + " (no link: the second brain " + b.name + " has no mirror_url)"

def stub(content, old, new, why):
    fm, body = split_fm(content)
    tags = re.search(r"(?m)^tags:\n((?:[ \t]+- .*\n?)+)", fm + "\n")
    title = re.search(r"(?m)^name:[ \t]*(.+)$", fm)
    label = (title.group(1).strip().strip("'\"") if title else new.rsplit("/", 1)[-1])
    today = datetime.datetime.now(_cfg.tz()).strftime("%Y-%m-%d")
    return ("---\ntype: redirect\ntitle: moved → " + new + "\nredirect_to: " + new + "\n" + ("tags:\n" + tags.group(1).rstrip("\n") + "\n" if tags else "") + "---\n\n"
            "# moved → " + new + "\n\n[[" + new + "]] — " + _link(label, new) + "\n\n"
            "- **" + today + "** | " + str(_cfg.get("pages", "timeline_source") or "stackshot") + " — Moved to " + new + ": " + why + "\n")

def body_of(content): return split_fm(content)[1].rstrip()

def _live_sessions():
    """The sessions sala lists now as (names, aliases), or None when sala cannot be read (no fleet store, no sala, a failing call): then a name line counts as live."""
    try:
        import anchors as _anc
        got = _anc.sala_sessions()
    except Exception: return None
    return got if got and got[0] else None

def agents_gap(content, new, old_content=None):
    """None when the page at `new` is fine, else (why, fix): a project with no one to take its items. `projects.agent_gap` is the one rule (the daily page agent lines check uses it too): `type: project`, active
    (not retired, done or moved), no sub-page (a key under another page of the registry, or a `hub:` line; a `parent:` line is no sub-page for the registry, so it is none here), no front agent on the `agents:` map, and no
    session of its own: a `display-name:` that names a live sala session, or one that starts with it, is a one-session page and passes, unless that name belongs to another project (it starts with that project's name,
    not this page's). A page with no frontmatter, or one that cannot be read, is no project here. `old_content` is the page at the old slug: when it was no project there the reason says the type changed."""
    import pages as _pages, projects as _prj, anchors as _anc
    try:
        fm = _pages.frontmatter_text(content)
        flat, back = _pages.split_agents(fm.get("agents")); who, role = _pages.keeper_of(new, {new: fm})
    except Exception: return None
    entry = {"type": fm.get("type") or "", "status": fm.get("status") or "", "title": fm.get("title") or "", "hub": fm.get("hub") or "", "agents": flat, "back_agents": back, "session": who, "role": role}
    live = _live_sessions()
    gap = _prj.agent_gap(new, entry, _anc.registry(), live)
    if not gap: return None
    was = ""
    if old_content is not None:
        try: t = str(_pages.frontmatter_text(old_content).get("type") or "").strip().lower()
        except Exception: t = ""
        was = f" (it was type: {t or 'unset'} at the old slug)" if t != "project" else ""
    if gap["kind"] == "foreign-name":
        return (f"{new}'s only session {gap['name']} is named for {gap['other']}, not for this page, and no agents map lists it{was}",
                f"give the page its own agents map and -main agent on {new} (ask the scope's general -main agent)")
    what = "only background agents" if gap["kind"] == "no-front-agent" else "no agents map"
    return (f"{new} is a top-level type: project page{was} with {what}" + (f" and a name line session {gap['name']} that is not live" if gap["name"] else " and no session of its own") + " (no front agent, no -main agent)",
            f"add the agents map with its -main agent on {new} (ask the keeper or the project's -main agent)")

def main():
    a = sys.argv[1:]; verb = a.pop(0) if a else ""
    why = a.pop(a.index("--why") + 1) if "--why" in a else f"renamed on {_cfg.owner()}'s go."; a = [x for x in a if x != "--why"]
    parent = a.pop(a.index("--parent") + 1) if "--parent" in a else None; a = [x for x in a if x != "--parent"]
    no_agents_ok = "--no-agents-ok" in a; a = [x for x in a if x != "--no-agents-ok"]
    _agents_check = {"off": no_agents_ok}
    def check_on():
        """True when the agents check runs. Asked only where a check is about to run (after the plain-pages refusal, the argument checks and the first page read), so a refused run prints only its refusal. With no page registry a would-be sub-page cannot be told from a top-level project, so the check is skipped with one printed note."""
        if _agents_check["off"]: return False
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import anchors as _reg
        if not _reg.registry():
            print("note: the page registry is not readable here (empty or missing), so the check for a project page with no agents map is skipped; run it where the registry is, or add --no-agents-ok to silence this")
            _agents_check["off"] = True; return False
        return True
    tops = [tuple(x.split("=", 1)) for x in a]
    if verb not in ("plan", "copy", "stub") or not tops: sys.exit(__doc__)
    pairs = [(m, new + m[len(old):]) for old, new in tops for m in family(old)]
    os.makedirs(STATE, exist_ok=True); bad = 0
    if verb == "stub":
        # The items' and the anchors' keys move between copy and stub. A stub written while something still names the old key
        # leaves it pointing at a page the registry no longer lists (an anchor stranded by a rename done by hand).
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import anchors as _anc
        olds = {old for old, _ in pairs}
        left = [f"anchor {e.get('url')} under {k}" for k, es in _anc.load().items() if k in olds for e in es]
        left += [f"item {t['gid']} ({t.get('status')}) has project {_anc.project_of(t)}" for t in _anc.items() if t.get("status") != "completed" and _anc.project_of(t) in olds]
        if left:
            print("FAIL stub: still pointing at the old key, move these first (items: update(project=<new key>), or move the project's page in the record (project_verbs move-page) and the items that store its id follow; anchors: add under the new key, remove under the old):")
            for x in left: print("  " + x)
            sys.exit(1)
        refused = []        # a project page with no agent at its new slug: nothing is stubbed (the check runs before the first write)
        for old, new in tops if not no_agents_ok else []:
            oc, _r = get(old); nc, _r = get(new)
            if oc is None or nc is None or re.search(r"(?m)^type:[ \t]*redirect", split_fm(oc)[0]): continue      # the loop below reports an unreadable page, or skips a redirect
            if not check_on(): break
            gap = agents_gap(nc, new, oc)
            if gap: refused.append(gap)
        if refused:
            for why_not, fix in refused:
                print(f"FAIL stub: {why_not}. {fix[0].upper() + fix[1:]}, then run stub again; --no-agents-ok if it has none on purpose.")
            sys.exit(1)
    for old, new in pairs:
        top = (old, new) in tops; sf = os.path.join(STATE, old.replace("/", "__") + ".json")
        content, rev = get(old)
        if content is None: print(f"FAIL {old}: unreadable"); bad += 1; continue
        if re.search(r"(?m)^type:[ \t]*redirect", split_fm(content)[0]): print(f"skip {old}: already a redirect"); continue
        if verb in ("plan", "copy"):
            out = transform(content, old, new, pairs, parent if top else None)
            ex, _ = get(new)
            if ex is not None and body_of(ex) != body_of(out): print(f"FAIL {new}: a different page already exists there"); bad += 1; continue
            print(f"{'plan' if verb == 'plan' else 'copy'} {old} → {new}  ({len(content.encode())} B, {sum(1 for x, y in zip(content.split(chr(10)), out.split(chr(10))) if x != y) + abs(len(content.split(chr(10))) - len(out.split(chr(10))))} line(s) differ)" + ("  [already there]" if ex is not None else ""))
            if top and check_on():
                gap = agents_gap(ex if ex is not None else out, new, content)
                if gap: print(f"  WARN {gap[0]}: {gap[1]} before stub (stub refuses without it; --no-agents-ok if it has none on purpose)")
            if verb == "plan":
                open(os.path.join(STATE, new.replace("/", "__") + ".planned.md"), "w", encoding="utf-8").write(out); continue
            if ex is None:
                rc, res = gb(["put", new], stdin=out)
                if rc != 0 or '"error"' in res: print(f"FAIL put {new}: {res.strip()[:300]}"); bad += 1; continue
            back, _ = get(new)
            if back is None or body_of(back) != body_of(out): print(f"FAIL {new}: read-back differs from what was written"); bad += 1; continue
            json.dump({"old": old, "new": new, "rev": rev}, open(sf, "w")); print(f"  ok: {new} reads back identical")
        else:
            try: st = json.load(open(sf))
            except Exception: print(f"FAIL {old}: no copy on record — run copy first"); bad += 1; continue
            if st.get("rev") != rev: print(f"FAIL {old}: changed since the copy (revision {rev[:8]} ≠ {str(st.get('rev'))[:8]}) — run copy again"); bad += 1; continue
            if get(new)[0] is None: print(f"FAIL {old}: {new} is not there"); bad += 1; continue
            rc, res = gb(["put", old, "--expected-revision", rev], stdin=stub(content, old, new, why))
            if rc != 0 or '"error"' in res: print(f"FAIL stub {old}: {res.strip()[:300]}"); bad += 1; continue
            print(f"stub {old} → {new}")
            try:        # the project's permanent id follows the page (projects.py): the old page leaves the registry, the new key must not get a fresh id
                import projects as _prj
                _prj.ensure_ids([old])      # a page the id file has never seen gets its id now, so there is one to move
                print(f"  project id {_prj.rename(old, new)} now stands for {new}")
            except Exception as e:
                print(f"  FAIL project id of {old} not moved to {new} ({e}); run: python3 {os.path.dirname(os.path.abspath(__file__))}/projects.py rename {old} {new}"); bad += 1
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    try: main()
    except PlainPages as e: print("FAIL " + str(e)); sys.exit(1)
