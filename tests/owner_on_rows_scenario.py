"""Scenario test for the owner on the item rows (Board.row_line, Board.row_contact in ui/render.py; the line above a row's title, `.ir-proj`, in ui/kit.py) — fixture data, no live store, no network, no server.

A row of the board's lists names the item's owner beside its project: `project · owner`, in the same small quiet line. The owner is the name the item page's side column shows (Board.owner_row, which reads
the item's contact: the front agent to talk to about it), resolved by the one function the server hands the board (`contact_of`, the server's `_contact_label`), never a second resolver. It is a link to the
session's view while the session has a live pane and plain text otherwise (Board.sess_html, as every page draws a session).

Covers:
  * home (Your move, On agent, Waiting) and the Closed page (New, Last 14 days): `project · owner` with the owner a link while its pane lives, plain text without one; an item with no owner shows the project
    name alone (the line as it was); an item with neither has no line;
  * a project page: the owner stands alone on the line (the project name is redundant there), on the open lists and on the completed one; an item with no owner has no line;
  * the name is the side column's: the derived contact wins over the stored one, as on the item page, and without a resolver the stored contact is read, as the side column does;
  * at most one lookup per row: the resolver runs once per item in a render, an item drawn twice on a page (the Closed page's New and Last 14 days) included, and only for the rows the page draws;
    a resolver that fails leaves the row on the stored contact and the page whole;
  * the stylesheet keeps the owner as quiet as the project: the muted colour, the accent on hover.

    tests/run-suite owner_on_rows        → exit 0 / 1"""
import datetime, json, logging, os, pathlib, re, sys
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
sys.path.insert(0, STACK)
tmp = _scratch.mkdtemp(prefix="ownrows-"); T = pathlib.Path(tmp)
toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml
toml = toml.replace('session_view = ""', 'session_view = "https://sala.example.org/#s={name}"', 1); assert "sala.example.org" in toml
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^owner = "the owner"', 'owner = "Oliver"', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/site", "brain/projects", "secrets", "touch"): (T / d).mkdir(parents=True)
ZONE = datetime.timezone(datetime.timedelta(hours=4))
NOW = datetime.datetime(2026, 10, 27, 10, 0, tzinfo=ZONE)
now = NOW.timestamp(); H, D = 3600.0, 86400.0
FRONT, BACK = "00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002"
LIVE, GONE, OTHER = "team-front", "team-gone", "team-other"      # LIVE has a pane (the fleet lists it now), GONE is a name no pane carries, OTHER stands for a stored contact the resolver overrides
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({FRONT: {"name": LIVE, "machine": "a", "seen": now, "url": "https://example.invalid/front"},
                                                     BACK: {"name": "team-back", "machine": "a", "seen": now, "url": "https://example.invalid/back"}}))
(T / "store/projects.json").write_text(json.dumps({"pages": {
    "projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project", "session": LIVE, "status": "active", "board": [], "board_open": 0,
                       "agents": {LIVE: "the front", "team-back": "the back"}, "back_agents": {"team-back": "the back"}},
    "projects/alpha/sub-work": {"title": "Sub work", "name": "Sub work", "org": "home", "tags": [], "type": "project", "session": LIVE, "status": "active", "board": [], "board_open": 0}}}))
(T / "store/project-record.json").write_text(json.dumps({"projects": {f"prj_{0xcafe:08x}": {"name": "Alpha", "type": "project", "status": "active", "page": "projects/alpha"}}}))
(T / "brain/projects/alpha.md").write_text(f"---\ntitle: Alpha\ndisplay-name: {LIVE}\nagents:\n  {LIVE}: the front\n  background:\n    team-back: the back\n---\n\n# Alpha\n")
(T / "store/next-id").write_text("900"); (T / "store/anchors.json").write_text("{}")
(T / "state").mkdir(exist_ok=True); (T / "state/waiting.json").write_text(json.dumps({"baseline": now - 100 * D, "seen": {}, "reported": []}))


def item(i, subject, status="open", age=3 * H, project="projects/alpha", **meta):
    meta = {"owner": BACK, "next": "team-back: do the thing", **meta}
    if project: meta["project"] = project
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": subject, "description": "A fixture item.", "status": status, "updated": now - age, "state_updated": now - age,
                                                    "confirmed": now - age, "metadata": meta}))


# a decision on the owner (Your move), an item on an agent, a wait, each with an owner or without; two closed ones, one of them an agent's close the Closed page lists under New
item(1, "[home] a decision for the owner", needs=["decision"], ask="Decide: ship it? · Recommend: yes · Stakes: low · By: Fri", next="Oliver: answer the ask", contact=LIVE)          # owner with a live pane
item(2, "[home] an item on an agent", contact=GONE)                                                                                                                            # owner with no pane
item(3, "[home] an item with no owner")                                                                                                                                        # no contact
item(4, "[home] a wait", hold=True, wake=(NOW + datetime.timedelta(days=3)).strftime("%Y-%m-%d"), post_wake_mover="team-back", contact=LIVE)                                      # Waiting
item(5, "[home] stored contact is not the owner", contact=OTHER)                                                                                                               # the resolver names LIVE
item(6, "[home] closed by an agent", status="completed", age=2 * H, outcome="done", reason="shipped", contact=LIVE)                                                              # New and Last 14 days
item(7, "[home] closed earlier", status="completed", age=3 * D, outcome="done", reason="shipped", contact=GONE)                                                                  # Last 14 days only
item(8, "[home] closed with no owner", status="completed", age=4 * D, outcome="done", reason="shipped")
item(9, "[home] no project, an owner", project="", contact=LIVE)                                                                                                                # no project: the owner alone, on home
item(10, "[home] filed on a sub-page", project="projects/alpha/sub-work", contact=LIVE)                                                                                          # a sub-page of Alpha, with an owner
item(11, "[home] closed, filed on a sub-page", project="projects/alpha/sub-work", status="completed", age=1 * H, outcome="done", reason="shipped", contact=GONE)                   # New and Last 14 days
logging.disable(logging.INFO)
from stackshot.web import landed
landed.record("a6", now - 2 * H, "done", by="team-back", project="projects/alpha")
landed.record("a11", now - 1 * H, "done", by="team-back", project="projects/alpha/sub-work")

fails, ran = [], []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:900]}" if got is not None else ""))
from stackshot.web.ui import render, kit

RESOLVED = {"a5": LIVE}      # the server's resolver, as a fixture: the derived contact where one differs from the stored one, else the stored one
def resolver(r): return RESOLVED.get(r["gid"], str((r.get("metadata") or {}).get("contact") or ""))
class Counting:
    """A contact_of that counts its calls per item."""
    def __init__(self, fn=resolver): self.fn, self.calls = fn, []
    def __call__(self, r): self.calls.append(r["gid"]); return self.fn(r)
def board(**kw): return render.Board(str(T / "store"), now=NOW, **kw)

LI = re.compile(r'<li class="irow[^"]*"[^>]*>(.*?)</li>', re.S)
def lines(page):
    """[(item number, the inner html of the row's project line or None)] for every row of the page, in document order."""
    out = []
    for body in LI.findall(page):
        m = re.search(r'href="/items/a?(\d+)"', body)
        pj = re.search(r'<div class="ir-proj">(.*?)</div>', body, re.S)
        out.append((int(m.group(1)), pj.group(1) if pj else None))
    return out
def of(page, n, which=0):
    """The project line of the which-th row of item n on the page."""
    got = [pj for i, pj in lines(page) if i == n]
    return got[which] if len(got) > which else "(no row)"
PROJECT = r'<a class="pjl" href="/projects/alpha">[^<]+</a>'
LIVE_LINK = rf'<a class="pjo" href="https://sala\.example\.org/#s={LIVE}" target="_blank" rel="noopener" title="[^"]*">{LIVE}</a>'
GONE_TEXT = rf'<span class="pjo">{GONE}</span>'
both = lambda owner: re.compile(rf'{PROJECT} · {owner}')

home = board(contact_of=resolver).html()
closed = board(contact_of=resolver).landed_html()
proj = board(contact_of=resolver).routing_html("projects/alpha")

# ---- home: project · owner
check("home, an owner with a live pane: the project's link, then the owner as a link to the session's view, in the one line above the title",
      both(LIVE_LINK).fullmatch(of(home, 1) or "") and both(LIVE_LINK).fullmatch(of(home, 4) or ""), (of(home, 1), of(home, 4)))
check("home, an owner with no pane: the same line with the name as plain text (no link)", both(GONE_TEXT).fullmatch(of(home, 2) or "") and "<a" not in of(home, 2).split(" · ", 1)[1], of(home, 2))
check("home, no owner: the project's name alone, the line as it was", re.fullmatch(PROJECT, of(home, 3) or ""), of(home, 3))
check("home, no project but an owner: the owner alone", re.fullmatch(LIVE_LINK, of(home, 9) or ""), of(home, 9))
check("the line is before the title line, in a div of its own, in every row of the lists", all(b.index('class="ir-proj"') < b.index('class="ir-top"') for b in LI.findall(home) if 'class="ir-proj"' in b) and len(lines(home)) >= 5, len(lines(home)))
check("the name is the one the resolver derives, not the stored contact: item 5 stores another name and the resolver names the live session", both(LIVE_LINK).fullmatch(of(home, 5) or "") and OTHER not in home, of(home, 5))

# ---- Closed: New and Last 14 days
check("Closed, New: project · owner (the owner linked, as its pane lives)", both(LIVE_LINK).fullmatch(of(closed, 6, 0) or ""), of(closed, 6, 0))
check("Closed, Last 14 days: project · owner for an owner with a live pane, plain text without one, the project alone without an owner",
      both(LIVE_LINK).fullmatch(of(closed, 6, 1) or "") and both(GONE_TEXT).fullmatch(of(closed, 7) or "") and re.fullmatch(PROJECT, of(closed, 8) or ""), (of(closed, 6, 1), of(closed, 7), of(closed, 8)))
check("Closed lists item 6 twice (New and Last 14 days) and every row has its line", [i for i, _ in lines(closed)].count(6) == 2 and all(pj for _, pj in lines(closed)), lines(closed))

# ---- the project is the top-level one, never the sub-page the item is filed on
check("home: a row filed on a sub-page names the top-level project, in name and link, with the owner beside it; a row on a top-level page reads as before",
      both(LIVE_LINK).fullmatch(of(home, 10) or "") and ">home/Alpha</a>" in of(home, 10) and "Sub work" not in "".join(pj or "" for _i, pj in lines(home)) and both(LIVE_LINK).fullmatch(of(home, 1) or ""), (of(home, 10), of(home, 1)))
check("Closed: a row filed on a sub-page names the top-level project (New and Last 14 days), the owner beside it as plain text or a link as its pane lives",
      all(both(GONE_TEXT).fullmatch(of(closed, 11, k) or "") and ">home/Alpha</a>" in of(closed, 11, k) for k in (0, 1)) and "Sub work" not in "".join(pj or "" for _i, pj in lines(closed)), [of(closed, 11, k) for k in (0, 1)])
check("a project page keeps its sub-page badge: the completed row filed on the sub-page names it on its who line", any("Sub work" in b and "ir-who" in b for b in LI.findall(proj) if "/items/a11" in b), None)

# ---- a project page: the owner alone
check("project page, open rows: the owner alone on the line (a link with a live pane, plain text without), no project name and no separator",
      re.fullmatch(LIVE_LINK, of(proj, 1) or "") and re.fullmatch(GONE_TEXT, of(proj, 2) or "") and re.fullmatch(LIVE_LINK, of(proj, 4) or "") and re.fullmatch(LIVE_LINK, of(proj, 5) or ""),
      [of(proj, n) for n in (1, 2, 4, 5)])
check("project page, no owner: no line at all", of(proj, 3) is None, of(proj, 3))
check("project page, completed rows: the owner alone as well", re.fullmatch(LIVE_LINK, of(proj, 6) or "") and re.fullmatch(GONE_TEXT, of(proj, 7) or "") and of(proj, 8) is None, (of(proj, 6), of(proj, 7), of(proj, 8)))
check("project page: no row names the project", 'class="pjl"' not in proj[proj.find('<section id="items">'):] if '<section id="items">' in proj else 'class="pjl"' not in "".join(LI.findall(proj)),
      [i for i, pj in lines(proj) if pj and "pjl" in pj])

# ---- the name is the side column's
b = board(contact_of=resolver)
same = []
for g in ("a1", "a2", "a4", "a5", "a6", "a7"):
    r = b.item(g); side = re.sub(r"<[^>]+>| ↗", "", b.owner_row(r, resolver(r))[1]); row = re.sub(r"<[^>]+>", "", b.row_line(r, project=False))
    same.append((g, side, row))
check("the row names the same session as the item page's side column (owner_row), derived contact first", all(s == rw and s for _g, s, rw in same), same)
check("…and the same link: the row's owner is the side column's value but for the arrow", all(b.sess_html(resolver(b.item(g))) in (b.row_line(b.item(g), project=False)) or b.sess_html(resolver(b.item(g)), cls="pjo") == b.row_line(b.item(g), project=False) for g in ("a1", "a2")),
      b.row_line(b.item("a1"), project=False))
plain = board()      # no resolver: the stored contact, as the side column reads it
check("without a resolver the stored contact is read (as the side column does): item 5 shows the stored name, item 3 has none",
      f'>{OTHER}<' in of(plain.html(), 5) and re.fullmatch(PROJECT, of(plain.html(), 3) or ""), (of(plain.html(), 5), of(plain.html(), 3)))

# ---- at most one lookup per row
def rows_of(page): return [i for i, _ in lines(page)]
for name, draw in (("home", lambda c: board(contact_of=c).html()), ("Closed", lambda c: board(contact_of=c).landed_html()), ("a project page", lambda c: board(contact_of=c).routing_html("projects/alpha"))):
    c = Counting(); page = draw(c); drawn = rows_of(page)
    check(f"{name}: the resolver runs once per item and for the rows the page draws, no more ({len(c.calls)} lookups, {len(drawn)} rows, {len(set(drawn))} items)",
          len(c.calls) == len(set(c.calls)) and {int(g[1:]) for g in c.calls} == set(drawn) and len(c.calls) <= len(drawn), (sorted(c.calls), drawn))
check("Closed draws item 6 twice and looks it up once", [i for i, _ in lines(closed)].count(6) == 2 and Counting.__name__ == "Counting"
      and (lambda c: (board(contact_of=c).landed_html(), c.calls.count("a6"))[1])(Counting()) == 1)
broken = Counting(lambda r: 1 / 0)
page = board(contact_of=broken).html()
check("a resolver that fails leaves the row on the stored contact and the page whole", len(broken.calls) == len(set(broken.calls)) > 0 and both(LIVE_LINK).fullmatch(of(page, 1) or "") and re.fullmatch(PROJECT, of(page, 3) or ""), (of(page, 1), of(page, 3)))

# ---- the stylesheet: as quiet as the project
css = kit.CSS
check("the line is muted and the owner's link is muted with the accent on hover, as the project's is",
      re.search(r"\.ir-proj\{[^}]*color:var\(--mut\)", css) and ".ir-proj a.pjo{color:var(--mut)}" in css and ".ir-proj a.pjo:hover{color:var(--acc)}" in css and ".ir-proj a.pjl{color:var(--mut)}" in css, None)
check("kit.row draws whatever project_html it is given in the one line, and none when empty",
      kit.row(href="/items/1", rid="item-1", title="t", project_html='<a class="pjo" href="#">x</a>').count('class="ir-proj"') == 1 and 'ir-proj' not in kit.row(href="/items/1", rid="item-1", title="t"))

print(f"ok: owner on rows scenario, {len(ran)} checks" if not fails else f"FAILED: owner on rows scenario, {len(ran)} checks, {len(fails)} failed"); sys.exit(1 if fails else 0)
