"""page_keeper.py — the one-time pass that renames a page's `session:` line (the field was renamed, and
it became `display-name:` in an earlier change; plus `agent:` for a sub-page an agent keeps).

  page_keeper.py plan             what the pass would do to every page that carries `session:`; reads the database, changes nothing
  page_keeper.py apply [key …]    do it (all pages, or the keys given): one frontmatter line per page, the body byte for byte,
                                  put with the revision that was read, then read back and compared

What a `session:` line becomes:
  on a top-level page (a hub)                                   → `display-name: <same name>`
  on a sub-page kept by a session other than its hub's named one → `agent: <same name>`
  on a sub-page kept by its hub's own named session              → the line is dropped: the registry gives such a page to the hub's
                                                                   named session, so the hub is the one place that names it
The registry (pages.py) reads all three keys, so a page that is not converted keeps working. It runs on the server box only (the gbrain CLI)."""
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]
import json, os, re, sys

from stackshot.projects import rename_page as rp      # gb(), get(), split_fm(): the byte-exact read and put the page moves use
from stackshot.core import config as _cfg

REG = os.path.join(str(_cfg.path("paths", "store")), "projects.json")
LINE = re.compile(r"(?m)^session:[ \t]*(.*?)[ \t]*$")
KEEP = re.compile(r"(?m)^(display-name|session):[ \t]*(.*?)[ \t]*$")


def val(s): return s.strip().strip("'\"")


def hub_keeper(key, fms):
    """The session named by the nearest page above `key` that names one (its `display-name:` or old `session:` line), '' if none."""
    parts = key.split("/")
    for i in range(len(parts) - 1, 1, -1):
        p = "/".join(parts[:i]); fm = fms.get(p)
        if fm is None: continue
        if re.search(r"(?m)^agent:", fm): continue
        m = KEEP.search(fm)
        if m and val(m.group(2)): return val(m.group(2))
    return ""


def decide(key, fm, fms):
    """→ (what, new frontmatter) for a page whose frontmatter carries `session:`; (None, fm) when it does not."""
    m = LINE.search(fm)
    if not m or not val(m.group(1)): return None, fm
    who = val(m.group(1))
    if key.count("/") == 1: return f"display-name: {who}", LINE.sub(lambda _m: f"display-name: {who}", fm, count=1)
    up = hub_keeper(key, fms)
    if up and up == who:
        new = re.sub(r"(?m)^session:[^\n]*\n?", "", fm, count=1)
        return f"line dropped (the hub's named session is {up})", new.rstrip("\n")
    return f"agent: {who}" + ("" if up else "  (no page above it names a session)"), LINE.sub(lambda _m: f"agent: {who}", fm, count=1)


def load(keys):
    out = {}
    for k in keys:
        content, rev = rp.get(k)
        if content is None: print(f"  ! {k}: could not be read"); continue
        fm, body = rp.split_fm(content); out[k] = (fm, body, rev)
    return out


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd not in ("plan", "apply"): print(__doc__); return 1
    if _cfg.page_flavor() != "gbrain": raise rp.PlainPages(rp.PLAIN_MSG)    # before the registry is read: plain pages have no gbrain to work on
    reg =json.load(open(REG, encoding="utf-8"))["pages"]
    pages = load(sorted(reg)); fms = {k: v[0] for k, v in pages.items()}
    todo = [(k, *decide(k, fms[k], fms)) for k in sorted(pages)]
    todo = [(k, what, new) for k, what, new in todo if what]
    only = set(argv[2:])
    if only: todo = [t for t in todo if t[0] in only]
    for k, what, _new in todo: print(f"  {k:52} → {what}")
    print(f"{len(todo)} page(s) carry `session:`" + ("" if cmd == "apply" else "; nothing changed (plan)"))
    if cmd == "plan": return 0
    done = failed = 0
    for k, what, new in todo:
        fm, body, rev = pages[k]
        rc, res = rp.gb(["put", k, "--expected-revision", rev], stdin="---\n" + new + "\n---\n" + body)
        if rc != 0 or '"status":"error"' in res.replace(" ", ""):
            failed += 1; print(f"  ! {k}: put refused — {res.strip()[:160]}"); continue
        c2, _r2 = rp.get(k)
        fm2, body2 = rp.split_fm(c2) if c2 else ("", "")
        same_body = body2 == body; gone = not LINE.search(fm2)
        ok = same_body and gone and (("display-name:" in what and re.search(r"(?m)^display-name:", fm2)) or ("agent:" in what and re.search(r"(?m)^agent:", fm2)) or "dropped" in what)
        if ok: done += 1
        else: failed += 1; print(f"  ! {k}: read back differs (body identical: {same_body}; old key gone: {gone})")
    print(f"applied {done}, failed {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    try: sys.exit(main(sys.argv))
    except rp.PlainPages as e: print("FAIL " + str(e)); sys.exit(1)
