"""Scenario test for the done check — fixture data, no live store, a fake
GitHub on a local port, no sala.

Covers: each check kind's parsing (pr_merged by owner/repo#n or URL, item_closed by any id form, lane (and sala_lane, its old name,
stored as lane; refused while [client] lanes_file is unset), unit_active) and
its refusal with the valid forms (an owner or repo of dots alone, ./x or a/.., is refused; a unit that would read as an option,
-Hhost.service or --foo.service, too); check="none" clears; a check alone owes no page and leaves the state clock; get shows it;
the create tool takes one. The gate: an update whose next hands the work to another session, a line in the form
`<session>: <action>` (a list marker before the name at most), is refused naming the session, the form and the fix (check= or
wake=, or the portal for a cached tool list without check), and passes with a check or a wake; the owner, the writer, a
session already in needs, a name in code or quotes, a longer name and a stored hand-off re-edited are not hand-offs, and
neither is a session's name anywhere else in next (inside a page slug, a #s= link, mid-sentence, before a colon mid-line, at
the start of a line with no colon); a write that only names a session in needs is not gated (that session's turn-end check
asks it); an update that hands nothing over is unaffected; a create is never refused. The pass: item_closed closes the item on
the next pass after the other item completes, outcome done, the reason naming the check, the live fields cleared, the
description kept, no page owed, the keeper of the owner's page told that it closed (the owner too when Oliver's words are on the item; the
sessions in its needs and the observers are not; an item that waited on it is released and told, as any close does); unit_active with a stubbed runner that records the argv (`--` before the unit;
inactive: open; not-found: an error logged once, shown by get, never a close; active: closed); the lost update: an item a
session wrote, closed or cleared the check of while its check ran is not closed on that pass (the write stands) and is closed
on a later pass if the check still holds; lane against a lanes.tsv and lane-default in the temp dir (a missing file is an
error, an empty [client] lanes_file too; items stored as sala_lane before the rename still read);
pr_merged against the fake GitHub (one GET per PR per [check] github_minutes, shared by two items; a 404 is an error tried
again; a PR closed unmerged fails the wait at once and tells the keeper; GitHub down backs off, doubling); a completed item is left alone; the descriptions carry the field.
A check met while needs holds decision closes nothing: one waiting note, once, and the close on the pass after the decision is cleared (needs external still closes);
clear_check removes a check as clear_needs removes needs (check="none" too; check="" is not passed, as needs="" is; a new check beside it stands), and the History says it.

    tests/run-suite check        → exit 0 / 1"""
import json, os, re, sys, pathlib, tempfile, threading, time, logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="checktest-"); T = pathlib.Path(tmp)


# ---- a fake GitHub: only the pull-request read the check makes, one repo "o/r"
class Fake:
    def __init__(self):
        self.merged = {7: False, 8: False, 9: False}   # the PRs that exist, and whether each is merged
        self.closed = set()                      # PRs closed without being merged
        self.down = False
        self.log = []                            # (method, path)
        self.lock = threading.Lock()


F = Fake()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, code, obj=None, headers=None):
        body = json.dumps(obj).encode() if obj is not None else b""
        self.send_response(code); self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items(): self.send_header(k, v)
        self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        path = urlparse(self.path).path
        with F.lock:
            F.log.append(("GET", path))
            if F.down: return self._send(503, {"message": "down"})
            if self.headers.get("Authorization") != "Bearer test-token": return self._send(401, {"message": "bad credentials"})
            m = re.fullmatch(r"/repos/o/r/pulls/(\d+)", path)
            if m and int(m.group(1)) in F.merged:
                n = int(m.group(1)); mg = F.merged[n]
                return self._send(200, {"number": n, "state": "closed" if (mg or n in F.closed) else "open", "merged": mg, "merged_at": "2026-10-14T10:00:00Z" if mg else None})
            return self._send(404, {"message": "Not Found"})


srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
API = f"http://127.0.0.1:{srv.server_address[1]}"
(T / "github.token").write_text("test-token\n")

toml = _instance.apply(_instance.base_toml())
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store (session links off)
toml, n = re.subn(r'(?m)^lanes_file = ""', f'lanes_file = "{tmp}/sala/lanes.tsv"', toml); assert n == 1   # a lane record in the temp dir (the example has none)
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
toml, n = re.subn(r'(?m)^api_url = "[^"]*"', f'api_url = "{API}"', toml); assert n == 1
toml, n = re.subn(r'(?m)^token_file = ""', f'token_file = "{tmp}/github.token"', toml); assert n == 1
toml, n = re.subn(r"(?m)^require_marks = true", "require_marks = false", toml); assert n == 1   # this suite is about the done check, its writes replace next wholesale; the checklist has its own suite: checklist
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
(T / "RULES.md").write_text("# rules\n\n" + "- a rule the connector serves, long enough to count as a rulebook.\n" * 20, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet", STACKSHOT_LANE_NAMES=f"{tmp}/sala/no-lane-names.json"); os.environ.pop("STACKSHOT_URL", None)   # no lane-names file: the fixed words alone (the suite is the same on a box that has the tool's file)
for d in ("store/a", "fleet/a", "state/anchor-hub", "brain/projects", "sala"): (T / d).mkdir(parents=True)
# The roster: the fleet's sessions (example-site keepers a page whose slug carries its name, as projects/example-site does on
# Oliver's board; kestrel-engineer is a name the fleet knows), and the alpha page's keeper and agents.
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(("home-owner", "home-stew", "team-back", "home-front", "home-other", "example-site", "kestrel-engineer"), 1)}
now0 = time.time()
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "seen": now0} for n, u in U.items()}))
(T / "store/projects.json").write_text(json.dumps({"pages": {"projects/alpha": {"title": "Alpha", "name": "Alpha", "org": "home", "tags": [], "type": "project",
                                                                                "session": "sparrow", "status": "active", "board": [], "board_open": 0,
                                                                                "agents": {"home-front": "the front", "team-back": "the back", "home-stew": "builds it"}, "back_agents": {"team-back": "the back", "home-stew": "builds it"}},   # the keeper is the page's builder home-stew; the name line sparrow is no session
                                                             "projects/example-site": {"title": "Example Site", "name": "Example Site", "org": "home", "tags": [], "type": "project",
                                                                                     "session": "example-site", "status": "active", "board": [], "board_open": 0}}}))
DESC = "- A thing\n- It lives here\n- Done when done"
def item(i, owner=U["home-owner"], status="open", **meta):
    (T / f"store/a/{i}.json").write_text(json.dumps({"id": str(i), "subject": f"[home] item {i}", "description": DESC, "status": status,
                                                       "updated": now0 - 60, "state_updated": now0 - 60, "confirmed": now0 - 60,
                                                       "metadata": {"owner": owner, **({} if {"needs", "hold", "after"} & set(meta) else {"mover": owner}), "project": "projects/alpha", **meta}}))
for i in range(1, 36):
    item(i, next="do the thing")
item(9, next="team-back: do it")                                    # a hand-off stored before the rule: never retro-refused
item(13, next="x", status="completed", outcome="done", reason="before", check="item_closed a3")   # a closed item with a check left on it: the pass leaves it alone
(T / "store/next-id").write_text("40"); (T / "store/anchors.json").write_text("{}")
(T / "brain/projects/alpha.md").write_text("---\ntitle: Alpha\ndisplay-name: sparrow\nagents:\n  home-front: the front\n  background:\n    team-back: the back\n    home-stew: builds it\n---\n\n# Alpha\n")
(T / "brain/projects/example-site.md").write_text("---\ntitle: Example Site\ndisplay-name: example-site\n---\n\n# Example Site\n")
sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:600]}" if got is not None else ""))
def rd(i): return json.loads((T / f"store/a/{i}.json").read_text())

from stackshot.web import server
from stackshot.service import event_waits as evwaits_svc
from stackshot.web.tools import anchors as _wt_anchors
from stackshot.web.tools import route as _wt_route
from stackshot.web.tools import complete as _wt_complete
from stackshot.web.tools import create as _wt_create
from stackshot.web.tools import get as _wt_get
from stackshot.web.tools import text as _wt_text
from stackshot.web.tools import update as _wt_update
from stackshot.service import telling
from stackshot.service import writes
server._publish = _wt_anchors._publish = _wt_route._publish = lambda: None
server._wt.cap_needs_owner = lambda: False     # this scenario sets waits far ahead; the cap on a session's wake has its own scenario (waiting)
server._refuse_if_owing = lambda debtor: None        # the page rule is not under test here
told = []
telling.tell_woken = lambda gid, owner, note, tag="wake": told.append((tag, gid, owner, note))
def refused(name, f, *want):
    try:
        out = f(); check(name, False, out)
    except server.ToolError as e:
        check(name, all(w in str(e) for w in want), str(e))
clock = [now0]
def tick(n=1):
    out = []
    for _ in range(n):
        clock[0] += 60; out += server._check_tick(clock[0])
    return out
def st(): return json.loads((T / "state/checks.json").read_text())
def gets(n): return [p for m, p in F.log if p == f"/repos/o/r/pulls/{n}"]
FORMS = "pr_merged <owner>/<repo>#<n>"

# ---- 1. parsing and refusal, each kind
server._update("a1", check="pr_merged example-owner/stackshot#171", sender="home-owner")
check("pr_merged owner/repo#n is stored as given", rd(1)["metadata"].get("check") == "pr_merged example-owner/stackshot#171", rd(1)["metadata"])
server._update("a1", check="pr_merged https://github.com/example-owner/stackshot/pull/14", sender="home-owner")
check("…and by URL, normalised", rd(1)["metadata"].get("check") == "pr_merged example-owner/stackshot#14", rd(1)["metadata"])
refused("pr_merged without the owner", lambda: server._update("a1", check="pr_merged stackshot#171", sender="home-owner"), "Refused: check", "pr_merged names the pull request as", FORMS, 'check="none" clears it')
refused("pr_merged with a shell tail", lambda: server._update("a1", check="pr_merged o/r#7; rm -rf /", sender="home-owner"), "Refused: check", FORMS)
for ref in ("./x#1", "../..#1", "a/..#1", "a/.#1", "https://github.com/../x/pull/1"):   # an owner or repo of dots alone is a path, not a repo
    refused(f"pr_merged {ref}: refused", lambda ref=ref: server._update("a1", check=f"pr_merged {ref}", sender="home-owner"), "Refused: check", "pr_merged names the pull request as")
server._update("a1", check="pr_merged o/r.js#7", sender="home-owner")
check("…a repo with a dot in its name is still a repo", rd(1)["metadata"].get("check") == "pr_merged o/r.js#7", rd(1)["metadata"])
server._update("a1", check="item_closed A3", sender="home-owner")
check("item_closed stores the normalised id", rd(1)["metadata"].get("check") == "item_closed a3", rd(1)["metadata"])
refused("item_closed naming the item itself", lambda: server._update("a1", check="item_closed a1", sender="home-owner"), "cannot name the item itself")
refused("item_closed naming an item that does not exist", lambda: server._update("a1", check="item_closed a99", sender="home-owner"), "a99, which does not exist")
refused("item_closed with no id", lambda: server._update("a1", check="item_closed zz", sender="home-owner"), "item_closed names a board item by its id")
server._update("a1", check="  lane   home-x   api ", sender="home-owner")
check("lane stores session and lane, whitespace folded", rd(1)["metadata"].get("check") == "lane home-x api", rd(1)["metadata"])
server._update("a1", check="sala_lane home-y max", sender="home-owner")
check("sala_lane, the old name, is taken and stored as lane, the old lane word by its current code", rd(1)["metadata"].get("check") == "lane home-y subscription-1", rd(1)["metadata"])
server._update("a1", check="lane home-x aws-platform", sender="home-owner")
check("lane takes aws-platform (a hyphen inside the word)", rd(1)["metadata"].get("check") == "lane home-x aws-platform", rd(1)["metadata"])
server._update("a1", check="lane home-x awsplatform", sender="home-owner")
check("lane awsplatform, the old word, is stored as aws-platform", rd(1)["metadata"].get("check") == "lane home-x aws-platform", rd(1)["metadata"])
for bad_lane in ("-x", "x-", "a--b", "aws_platform", "Aws-platform"):
    refused(f"lane {bad_lane}: refused", lambda bl=bad_lane: server._update("a1", check=f"lane home-x {bl}", sender="home-owner"), "lane takes a session name and a lane")
check("a lane check stored before with the old word is shown as aws-platform",
      server._check_label("lane home-x awsplatform") == "lane home-x aws-platform" and server._check_label("sala_lane home-x awsplatform") == "sala_lane home-x aws-platform"
      and server._check_label("lane home-x api") == "lane home-x api" and server._check_label("unit_active a.service") == "unit_active a.service", server._check_label("lane home-x awsplatform"))
refused("lane without a lane", lambda: server._update("a1", check="lane home-x", sender="home-owner"), "lane takes a session name and a lane")
refused("lane with a lane that is not a lowercase word", lambda: server._update("a1", check="lane home-x API", sender="home-owner"), "lane takes a session name and a lane")
refused("…with no lane-names file the refusal still names valid lanes (the floor's codes and the plain ones)", lambda: server._update("a1", check="lane home-x API", sender="home-owner"),
        "lane takes a session name and a lane", "; lanes such as aws-platform, subscription-1, subscription-2, api, sdk")
check("a re-sent old lane word over a stored one is no changed check; another lane, or a cleared check, is",
      not server._check_changed("lane home-x max", "lane home-x max") and not server._check_changed("lane home-x subscription-1", "lane home-x max")
      and not server._check_changed("lane home-x max", "lane home-x subscription-1") and not server._check_changed(None, "") and not server._check_changed("unit_active a.service", "unit_active a.service")
      and server._check_changed("lane home-x api", "lane home-x max") and server._check_changed("", "lane home-x max") and server._check_changed("lane home-y max", "lane home-x max"))
server._cfg.CFG["client"]["lanes_file"] = ""
refused("lane with no lane record configured (no fleet tool)", lambda: server._update("a1", check="lane home-x api", sender="home-owner"), "[client] lanes_file is empty")
server._cfg.CFG["client"]["lanes_file"] = f"{tmp}/sala/lanes.tsv"
server._update("a1", check="unit_active stackshot.service", sender="home-owner")
check("unit_active stores the unit", rd(1)["metadata"].get("check") == "unit_active stackshot.service", rd(1)["metadata"])
server._update("a1", check="unit_active example-watch@x.timer", sender="home-owner")
check("…an instance unit and a timer too", rd(1)["metadata"].get("check") == "unit_active example-watch@x.timer", rd(1)["metadata"])
refused("unit_active without a type suffix", lambda: server._update("a1", check="unit_active stackshot", sender="home-owner"), "unit_active takes one systemd user unit name with its type suffix")
refused("unit_active with two words", lambda: server._update("a1", check="unit_active a b.service", sender="home-owner"), "unit_active takes one")
refused("unit_active with shell characters", lambda: server._update("a1", check="unit_active x;id.service", sender="home-owner"), "unit_active takes one")
refused("unit_active with a path", lambda: server._update("a1", check="unit_active ../x.service", sender="home-owner"), "unit_active takes one")
refused("unit_active with a unit that reads as an option (-H: another host)", lambda: server._update("a1", check="unit_active -Hhost.service", sender="home-owner"), "unit_active takes one")
refused("unit_active with a unit that reads as a long option", lambda: server._update("a1", check="unit_active --foo.service", sender="home-owner"), "unit_active takes one")
refused("an unknown kind", lambda: server._update("a1", check="shell true", sender="home-owner"), "not a check the server knows", FORMS, "item_closed <item id>", "lane <session> <lane>", "unit_active <unit>.service")
check("nothing above changed the stored check", rd(1)["metadata"].get("check") == "unit_active example-watch@x.timer", rd(1)["metadata"])
g = _wt_get.stackshot_get("a1")
check("get shows the check and that the server closes on it", "check: unit_active example-watch@x.timer (the server closes the item when it passes)" in g, g)
check("a check alone is a filing edit: the state clock stays, no page owed", rd(1)["state_updated"] == now0 - 60 and "a1" not in json.dumps(server._owed_load()), (rd(1)["state_updated"], server._owed_load()))
server._update("a1", check="none", sender="home-owner")
check('check="none" clears it', "check" not in rd(1)["metadata"], rd(1)["metadata"])
out = _wt_create._create(subject="[home] made with a check", description=DESC, project="projects/alpha", owner="home-owner", next="team-back: build it", needs=["team-back"], check="pr_merged o/r#8")
gid0 = re.search(r"created (\S+)", out).group(1)
check("create takes a check, and is never refused for a hand-off", gid0.startswith("s") and json.loads((T / f"store/s/{gid0[1:]}.json").read_text())["metadata"].get("check") == "pr_merged o/r#8" and "check: pr_merged o/r#8" in out, out)
refused("create refuses a bad check", lambda: _wt_create._create(subject="[home] bad check", description=DESC, project="projects/alpha", owner="home-owner", check="nope"), "not a check the server knows")

# ---- 2. the gate: a hand-off is a line of next in the form "<session>: <action>", a list marker before the name at most
refused("next handing the work to a background agent, no check, no wake: refused, naming the session, the form and the fix",
        lambda: server._update("a2", next="team-back: merge the PR", sender="home-owner"), "hands a2 to team-back", "a line of next in the form `<session>: <action>`", "check=<what closes it>", FORMS, "wake=YYYY-MM-DD",
        "Only when no check fits, add a date, wake=YYYY-MM-DD", "the item stays active in the new mover's lane", "as the backstop of this hand-off", "the date is no wait", "If this tool shows no check parameter", "codemode.stackshot_update({item_id, sender, next, check})")
try: server._update("a2", next="team-back: merge the PR", sender="home-owner"); _hand = ""
except server.ToolError as e: _hand = str(e)
check("the hand-off refusal steers to check first, the wake only when no check fits, and never mentions a hold or a park (Fri Oct 16th 2026)",
      _hand.index("Add check=") < _hand.index("Only when no check fits") < _hand.index("wake=YYYY-MM-DD") and not re.search(r"hold|park", _hand, re.I), _hand)
check("the refusal left the item as it was", rd(2)["metadata"].get("next") == "do the thing" and "check" not in rd(2)["metadata"], rd(2)["metadata"])
server._update("a2", next="team-back: merge the PR", check="pr_merged o/r#7", sender="home-owner")
check("…accepted with a check", rd(2)["metadata"].get("next") == "team-back: merge the PR" and rd(2)["metadata"].get("check") == "pr_merged o/r#7", rd(2)["metadata"])
server._update("a2", next="team-back: merge the PR, then deploy", sender="home-owner")
check("a re-edit of a stored hand-off is not asked again (the check stays)", rd(2)["metadata"].get("next").endswith("deploy") and rd(2)["metadata"].get("check") == "pr_merged o/r#7", rd(2)["metadata"])
server._update("a2", check="none", sender="home-owner")
check("clearing the check on a stored hand-off is not a new hand-off", "check" not in rd(2)["metadata"], rd(2)["metadata"])
refused("next handing it to the keeper: refused", lambda: server._update("a3", next="home-stew: rule on it", sender="home-owner"), "hands a3 to home-stew")
# a wake alone is a backstop, not a hold (items kept showing while their work was live): the wake the refusal offers is a backstop, never a hold
try:
    server._update("a3", next="home-stew: rule on it", sender="home-owner"); e_h = ""
except server.ToolError as e:
    e_h = str(e)
check("the hand-off refusal offers the date as the hand-off's backstop that leaves the item active in the new mover's lane, and never says hold",
      "wake=YYYY-MM-DD" in e_h and "as the backstop of this hand-off" in e_h and "the date is no wait" in e_h and "the item stays active in the new mover's lane" in e_h and "hold" not in e_h.lower(), e_h)
server._update("a3", next="home-stew: rule on it", wake="2099-01-01", sender="home-owner")
check("…accepted with a wake, which parks nothing: it stays the hand-off's backstop (a wake, no until, no hold) and the item stays active", rd(3)["metadata"].get("wake") == "2099-01-01" and "until" not in rd(3)["metadata"]
      and "hold" not in rd(3)["metadata"], rd(3)["metadata"])
server._update("a3", wake="none", sender="home-owner")
check("wake=\"none\" drops the reminder, nothing else", "wake" not in rd(3)["metadata"] and "hold" not in rd(3)["metadata"] and rd(3)["metadata"].get("next") == "home-stew: rule on it", rd(3)["metadata"])
server._update("a4", needs=["team-back"], sender="home-owner")
check("needs naming a session alone is not gated (its turn-end check asks it): accepted, the session told as before", rd(4)["metadata"].get("needs") == ["team-back"] and any(g == "a4" and t == "needs" for t, g, o, n in told), (rd(4)["metadata"], told))
server._update("a4", next="team-back: merge the PR", sender="home-owner")
check("next handing it to a session already in needs is not a new hand-off", rd(4)["metadata"].get("next") == "team-back: merge the PR", rd(4)["metadata"])
server._update("a16", needs=["team-back"], next="team-back: merge the PR", sender="home-owner")
check("next and needs naming the session in one write: in needs, so its turn-end check asks it; not gated", rd(16)["metadata"].get("needs") == ["team-back"] and rd(16)["metadata"].get("next") == "team-back: merge the PR", rd(16)["metadata"])
refused("next handing it to one session while needs names another: the one in next is a hand-off", lambda: server._update("a17", needs=["home-owner"], next="team-back: merge the PR", sender="home-owner"), "hands a17 to team-back", "a line of next in the form")
server._update("a17", needs=["home-owner"], next="team-back: merge the PR", check="item_closed a5", sender="home-owner")
check("…accepted with a check", rd(17)["metadata"].get("check") == "item_closed a5" and rd(17)["metadata"].get("needs") == ["home-owner"], rd(17)["metadata"])
server._update("a5", needs=["decision"], ask="Decide: x · Recommend: yes · Stakes: z · By: no date", sender="home-owner")
check("needs=decision alone is not a hand-off", rd(5)["metadata"].get("needs") == ["decision"], rd(5)["metadata"])
server._update("a6", needs=["home-owner"], sender="home-owner")
check("needs naming the owner is not a hand-off", rd(6)["metadata"].get("needs") == ["home-owner"], rd(6)["metadata"])
server._update("a7", next="team-back: merge it", sender="team-back")
check("next naming the writer itself is not a hand-off (the keeper's legacy line stays beside it)", rd(7)["metadata"].get("next") == "do the thing\nteam-back: merge it", rd(7)["metadata"])
server._update("a8", next="home-owner: read it back", sender="home-stew")
check("next naming the owner is not a hand-off (the keeper's legacy line stays beside it)", rd(8)["metadata"].get("next") == "do the thing\nhome-owner: read it back", rd(8)["metadata"])
server._update("a9", next="team-back: do it, then say so", sender="home-owner")
check("an item handed over before the rule, re-edited: not retro-refused", rd(9)["metadata"].get("next").endswith("say so"), rd(9)["metadata"])
server._update("a10", next="home-owner: ask in `team-back` later; see \"home-stew\" for why", sender="home-owner")
check("a name in code or quotes is not a hand-off", rd(10)["metadata"].get("next").startswith("home-owner: ask in"), rd(10)["metadata"])
server._update("a11", next="home-owner: team-back-main: write the brief", sender="home-owner")
check("a longer name containing a session's name is not that session", rd(11)["metadata"].get("next").startswith("home-owner: team-back-main"), rd(11)["metadata"])
server._update("a12", next="home-owner: write the doc", description="- A thing\n- It moved\n- Done when done", due="2026-12-01", sender="home-owner")
check("an update that hands nothing over is unaffected", rd(12)["metadata"].get("next") == "home-owner: write the doc" and rd(12)["metadata"].get("due") == "2026-12-01", rd(12)["metadata"])
refused("a plain session the fleet knows counts too", lambda: server._update("a14", next="home-other: run the export", sender="home-owner"), "hands a14 to home-other")
server._update("a14", next="home-other: run the export", check="unit_active export.service", sender="home-owner")
server._update("a14", check="none", sender="home-owner")           # cleared again: the pass below never runs the box's systemctl
server._update("a15", next="team-back: ship it", check="item_closed a16", sender="home-owner")
_wt_complete.stackshot_complete("a15", outcome="dropped", reason="not needed", description="- Not needed after all", sender="home-owner")
check("a close clears the check", "check" not in rd(15)["metadata"] and rd(15)["status"] == "completed", rd(15)["metadata"])
# A session's name elsewhere in next hands nothing over (the review of the first cut: the plain-word match fired on each of these)
for label, nx in (("inside a page slug", "update projects/example-site with the outcome"),
                  ("inside a #s= link", "read https://stackshot.example.com/#s=team-back before the merge"),
                  ("mid-sentence", "kestrel-engineer merged it; verify the deploy"),
                  ("before a colon but not at the start of the line", "then team-back: merge it"),
                  ("at the start of the line, no colon", "team-back merges the PR"),
                  ("a name with a colon inside a sentence", "the hand-off goes to team-back: see the page")):
    server._update("a18", next=f"home-owner: {nx}", sender="home-owner")
    check(f"a session's name {label} is not a hand-off", rd(18)["metadata"].get("next") == f"home-owner: {nx}" and "check" not in rd(18)["metadata"], rd(18)["metadata"])
for label, nx, who in (("<session>: <action>", "kestrel-engineer: do it", "kestrel-engineer"),
                       ("- <session>: <action>", "- team-back: do it", "team-back"),
                       ("1. <session>: <action>", "1. example-site: do it", "example-site"),
                       ("indented, with the colon spaced", "   team-back : do it", "team-back"),
                       ("on a later line of next", "verify the deploy\n- team-back: merge it", "team-back"),
                       ("two lines, two sessions", "team-back: build it\nhome-stew: rule on it", "home-stew, team-back")):
    refused(f"{label}: a hand-off, refused without a check or a wake", lambda nx=nx: server._update("a19", next=nx, sender="home-owner"), f"hands a19 to {who}")
check("the refusals left a19 as it was", rd(19)["metadata"].get("next") == "do the thing", rd(19)["metadata"])

# ---- 3. the pass: item_closed; the keeper is told (the one rule), the owner only with his words
item(20, check="item_closed a21", next="team-back: finish a21", needs=["team-back"], observers=["home-other"])
item(21)
item(22, after=["a20"], next="after a20")
told.clear()
check("a pass with nothing passed closes nothing", tick(1) == [] and rd(20)["status"] == "open")
check("a pass less than a minute after the last does nothing", server._check_tick(clock[0] + 30) == [])
_wt_complete.stackshot_complete("a21", outcome="done", reason="finished", description="- Finished", sender="home-owner")
told.clear()
closed = tick(1)
m = rd(20)["metadata"]
check("item_closed: the item closes on the next pass after the other completes", closed == ["a20"] and rd(20)["status"] == "completed", (closed, rd(20)))
check("outcome done, the reason naming the check", m.get("outcome") == "done" and m.get("reason") == "done check passed: item_closed a21", m)
check("the live fields are cleared, the description kept", not any(k in m for k in ("next", "needs", "check", "ask")) and rd(20)["description"] == DESC, (m, rd(20)["description"]))
check("the clocks moved", rd(20)["state_updated"] == clock[0] and rd(20)["confirmed"] == clock[0], rd(20))
about20 = [x for x in told if x[1] == "a20"]
check("the item's mover (the session in its needs) is told once (tag check), in one line naming the check; not the observer, not the creator",
      len(about20) == 1 and about20[0][0] == "check" and about20[0][2] == U["team-back"] and "its done check passed (item_closed a21)" in about20[0][3], told)
check("no page owed by anyone for the close", "a20" not in json.dumps(server._owed_load()), server._owed_load())
check("the item that waited on it is released and told, as any close releases it", "after" not in rd(22)["metadata"] and [x for x in told if x[1] == "a22"], (rd(22)["metadata"], told))
check("get shows the close", "outcome: done" in _wt_get.stackshot_get("a20") and "reason: done check passed: item_closed a21" in _wt_get.stackshot_get("a20"), _wt_get.stackshot_get("a20"))
check("a completed item with a check left on it is left alone", rd(13)["metadata"].get("reason") == "before")
check("a13 and a20 are not in the pass's state", not set(st()["items"]) & {"a13", "a20"}, st())

item(33, check="item_closed a34", next="team-back: finish a34", needs=["team-back"], answers=[{"ts": now0 - 30, "kind": "decision", "text": "go ahead", "via": "board"}], said=[{"tag": "Acked-by", "quote": "go ahead", "msg": "m1", "session": "s1", "ts": now0 - 30, "checked": True}])
item(34)
_wt_complete.stackshot_complete("a34", outcome="done", reason="finished", description="- Finished", sender="home-owner")
told.clear()
check("the pass closes it", tick(1) == ["a33"] and rd(33)["status"] == "completed", rd(33))
about33 = [x for x in told if x[1] == "a33"]
check("with his words on the item (a said entry) only the keeper is told; the owner is not (since Sat Oct 24th 2026 that close is a row on his For you list, not a message to the owner)",
      [x[2] for x in about33] == [U["team-back"]] and {x[0] for x in about33} == {"check"}, told)
check("…and the row is on the list: the item as closed by the server's done check",
      len([r for r in server._fy.rows() if r["gid"] == "a33" and r["kind"] == "closed"]) == 1, server._fy.rows())

item(37, check="item_closed a38", next="team-back: finish a38", needs=["team-back"], answers=[{"ts": now0 - 30, "kind": "decision", "text": "go ahead", "via": "board"}])
item(38)
_wt_complete.stackshot_complete("a38", outcome="done", reason="finished", description="- Finished", sender="home-owner")
told.clear()
check("the pass closes it", tick(1) == ["a37"] and rd(37)["status"] == "completed", rd(37))
about37 = [x for x in told if x[1] == "a37"]
check("a board answer alone is not his words about the close: the keeper is told, the owner is not (he answered on it, so it is a row on his list all the same)",
      [x[2] for x in about37] == [U["team-back"]] and {x[0] for x in about37} == {"check"} and len([r for r in server._fy.rows() if r["gid"] == "a37" and r["kind"] == "closed"]) == 1, told)
check("_owner_words: a board answer (text or choice) alone is none; a said entry counts", server._owner_words(rd(37)) == "" and server._owner_words({"metadata": {"answers": [{"choice": "Go"}]}}) == "" and server._owner_words(rd(33)) == "a said entry", (server._owner_words(rd(37)), server._owner_words(rd(33))))

# ---- 4. unit_active with a stubbed runner (the argv is what the stub sees: systemctl is never run)
calls = []
def unit_run(argv):
    calls.append(list(argv)); return UNIT[0]
server._unit_run = unit_run
UNIT = ["LoadState=loaded\nActiveState=inactive\n"]
item(23, check="unit_active stackshot.service", next="team-back: install it")
check("inactive: not closed, no error; the argv carries -- before the unit", tick(1) == [] and rd(23)["status"] == "open" and st()["items"]["a23"]["err"] == ""
      and calls == [["systemctl", "--user", "show", "-p", "LoadState", "-p", "ActiveState", "--", "stackshot.service"]], (st(), calls))
UNIT[0] = "LoadState=not-found\nActiveState=inactive\n"
check("not found: an error, never a close", tick(1) == [] and rd(23)["status"] == "open" and st()["items"]["a23"]["err"] == "unit stackshot.service is not-found", st())
check("the error is logged once and shown by get", server._CHECK_LOGGED.get("a23") == "unit stackshot.service is not-found"
      and "check: unit_active stackshot.service (the server closes the item when it passes; not readable at the last pass: unit stackshot.service is not-found)" in _wt_get.stackshot_get("a23"), _wt_get.stackshot_get("a23"))
UNIT[0] = ""
check("no answer: an error", tick(1) == [] and st()["items"]["a23"]["err"] == "systemctl gave no state for stackshot.service", st())
UNIT[0] = "LoadState=loaded\nActiveState=active\n"
check("active: closed with the reason", tick(1) == ["a23"] and rd(23)["metadata"].get("reason") == "done check passed: unit_active stackshot.service" and "a23" not in server._CHECK_LOGGED, rd(23)["metadata"])

# ---- 4b. a write during the check is not overwritten by the close (the lost update: the check's call can take 20 s)
item(30, check="unit_active stackshot.service", next="team-back: install it")
def unit_run_editing(argv):                       # a session's write lands while the check runs; the stub then steps aside
    calls.append(list(argv)); server._update("a30", next="team-back: install it, then say so", sender="home-owner"); server._unit_run = unit_run; return UNIT[0]
server._unit_run = unit_run_editing
check("an item written while its check ran is not closed on that pass, and the write stands", tick(1) == [] and rd(30)["status"] == "open"
      and rd(30)["metadata"].get("next") == "team-back: install it, then say so" and rd(30)["metadata"].get("check") == "unit_active stackshot.service" and not st()["items"].get("a30", {}).get("err"), (rd(30), st()))
check("…and is closed on the next pass, the check still holding", tick(1) == ["a30"] and rd(30)["metadata"].get("reason") == "done check passed: unit_active stackshot.service", rd(30)["metadata"])
item(31, check="unit_active stackshot.service", next="team-back: install it")
def unit_run_closing(argv):                       # a session closes the item itself while the check runs
    calls.append(list(argv)); _wt_complete.stackshot_complete("a31", outcome="dropped", reason="not needed", description="- Not needed after all", sender="home-owner"); server._unit_run = unit_run; return UNIT[0]
server._unit_run = unit_run_closing
check("an item a session closed while its check ran keeps that close", tick(1) == [] and rd(31)["status"] == "completed" and rd(31)["metadata"].get("outcome") == "dropped"
      and rd(31)["metadata"].get("reason") == "not needed" and "a31" not in st()["items"], (rd(31)["metadata"], st()))
item(32, check="unit_active stackshot.service", next="team-back: install it")
def unit_run_clearing(argv):                      # a session clears the check while it runs: the pass must not close on a check the item no longer carries
    calls.append(list(argv)); server._update("a32", check="none", sender="home-owner"); server._unit_run = unit_run; return UNIT[0]
server._unit_run = unit_run_clearing
check("an item whose check was cleared while it ran stays open", tick(1) == [] and rd(32)["status"] == "open" and "check" not in rd(32)["metadata"], rd(32))
check("…and the next pass, with no check on it, leaves it alone", tick(1) == [] and rd(32)["status"] == "open" and "a32" not in st()["items"], (rd(32), st()))

# ---- 5. lane against a lanes.tsv in the temp dir (the item stored as sala_lane, the name before the rename: still read)
item(24, check="sala_lane home-x api", next="team-back: move it")
item(25, check="lane home-y api", next="team-back: move it")
check("no lanes.tsv: an error, never a close", tick(1) == [] and "lane data not readable" in st()["items"]["a24"]["err"], st())
(T / "sala/lanes.tsv").write_text("home-w\tmax\nhome-x\tmax\n")
check("recorded on another lane: open", tick(1) == [] and st()["items"]["a24"]["err"] == "", st())
check("no row and no lane-default: the fallback is the subscription lane, so api does not pass", rd(25)["status"] == "open" and st()["items"]["a25"]["err"] == "")
(T / "sala/lanes.tsv").write_text("home-w\tmax\nhome-x\tapi\n"); (T / "sala/lane-default").write_text("api\n")
closed = tick(1)
check("the row on the lane, and the default lane for a session with no row: both close", sorted(closed) == ["a24", "a25"] and rd(24)["metadata"].get("reason") == "done check passed: sala_lane home-x api", (closed, rd(24)["metadata"]))
item(26, check="lane home-x api", next="team-back: move it")
server._cfg.CFG["client"]["lanes_file"] = ""
check("[client] lanes_file empty: no lane data, an error that says so", tick(1) == [] and st()["items"]["a26"]["err"] == "no lane data: [client] lanes_file is empty", st())
server._cfg.CFG["client"]["lanes_file"] = f"{tmp}/sala/lanes.tsv"
check("…and back with the file", tick(1) == ["a26"])

# ---- 5b. awsplatform and aws-platform are one lane: in any of the records, either word, both ways
(T / "sala/lanes.tsv").write_text("home-w\tmax\nhome-x\tapi\nhome-aws1\taws-platform\nhome-aws2\tawsplatform\nhome-aws3\tawsplatform\nhome-aws4\taws-platform\n")
(T / "sala/lane-default").write_text("awsplatform\n")
item(51, check="lane home-aws1 awsplatform", next="team-back: move it")       # stored with the old word, recorded with the new
item(52, check="lane home-aws2 aws-platform", next="team-back: move it")      # stored with the new word, recorded with the old
item(53, check="lane home-aws3 awsplatform", next="team-back: move it")       # old and old
item(54, check="lane home-aws4 aws-platform", next="team-back: move it")      # new and new (after it)
item(55, check="sala_lane home-nr aws-platform", next="team-back: move it")   # no row: lane-default, written with the old word
item(56, check="lane home-x aws-platform", next="team-back: move it")         # recorded on api: not the same lane
item(57, check="lane home-aws1 api", next="team-back: move it")               # the alias does not make other lanes equal
closed = tick(1)
check("awsplatform and aws-platform match in every pairing, a row or the lane-default", sorted(closed) == ["a51", "a52", "a53", "a54", "a55"], closed)
check("…another lane is still another lane", rd(56)["status"] == "open" and rd(57)["status"] == "open" and st()["items"]["a56"]["err"] == "")
check("…the reason shows aws-platform, never the old word", all("awsplatform" not in rd(i)["metadata"].get("reason", "") and "aws-platform" in rd(i)["metadata"].get("reason", "") for i in (51, 52, 53, 54, 55)),
      [rd(i)["metadata"].get("reason") for i in (51, 52, 53, 54, 55)])
for i in (56, 57): item(i, status="completed", outcome="dropped", reason="the lane check is done with")   # out of the passes that follow
(T / "sala/lanes.tsv").write_text("home-w\tmax\nhome-x\tapi\n"); (T / "sala/lane-default").write_text("api\n")

# ---- 5c. a lane renamed by its code (the fleet tool's lane-names file lists the old code as an alias; the fixed words stand in while that file is missing): old and new are one lane
(T / "sala/lanes.tsv").write_text("home-w\tmax\nhome-v\tsubscription-1\nhome-x\tapi\n")
item(58, check="lane home-w subscription-1", next="team-back: move it")      # stored with the new code, recorded with the old
item(59, check="lane home-v max", next="team-back: move it")                  # stored with the old code, recorded with the new
item(60, check="lane home-x subscription-1", next="team-back: move it")      # recorded on api: not the same lane
closed = tick(1)
check("an old lane code and its current one match, a row either way", sorted(closed) == ["a58", "a59"] and rd(60)["status"] == "open" and rd(59)["metadata"].get("reason") == "done check passed: lane home-v subscription-1", (closed, rd(59)["metadata"]))
item(60, status="completed", outcome="dropped", reason="the lane check is done with")
(T / "sala/lanes.tsv").write_text("home-w\tmax\nhome-x\tapi\n"); (T / "sala/lane-default").write_text("api\n")

# ---- 5d. the first codes of the two subscription lanes and their current codes are one lane each (max = subscription-1, team = subscription-2): a row of lanes.tsv, the first
# line of lane-default and the fallback with neither, a check stored with either word, both directions, with no lane-names file (the suite's state) and with one
NAMES = T / "sala/no-lane-names.json"          # the file STACKSHOT_LANE_NAMES names above: absent through the sections before this one
def lane_names(rows): NAMES.write_text(json.dumps({"lanes": rows}), encoding="utf-8")
def drop(*ids):
    for i in ids: item(i, status="completed", outcome="dropped", reason="the lane check is done with")     # out of the passes that follow
def lane_pairs(tag, first):
    (T / "sala/lanes.tsv").write_text("home-w\tmax\nhome-t\tteam\nhome-s1\tsubscription-1\nhome-s2\tsubscription-2\nhome-x\tapi\n")
    (T / "sala/lane-default").write_text("api\n")
    for k, c in enumerate(("lane home-w subscription-1", "lane home-s1 max", "lane home-t subscription-2", "lane home-s2 team", "lane home-w max", "lane home-s2 subscription-2")):
        item(first + k, check=c, next="team-back: move it")                    # a row either way, each pairing: all close
    for k, c in enumerate(("lane home-w subscription-2", "lane home-t max", "lane home-s1 team", "lane home-s2 subscription-1", "lane home-x subscription-1")):
        item(first + 6 + k, check=c, next="team-back: move it")                # max is not team, and neither is api
    closed = tick(1)
    check(f"5d {tag}: a row says one word, the check the other, for both lanes and both ways", sorted(closed) == sorted(f"a{first + k}" for k in range(6)), closed)
    check(f"5d {tag}: …never across the two lanes, and api is neither", all(rd(first + 6 + k)["status"] == "open" and st()["items"][f"a{first + 6 + k}"]["err"] == "" for k in range(5)))
    check(f"5d {tag}: …the reason shows the current code, never the first one", all("max" not in rd(first + k)["metadata"].get("reason", "") and "team" not in rd(first + k)["metadata"].get("reason", "") for k in range(6)),
          [rd(first + k)["metadata"].get("reason") for k in range(6)])
    drop(*range(first + 6, first + 11))
def lane_defaults(tag, first):
    (T / "sala/lanes.tsv").write_text("home-x\tapi\n")
    out = []
    for k, (word, default) in enumerate((("max", "subscription-1"), ("subscription-1", "max"), ("team", "subscription-2"), ("subscription-2", "team"), ("max", "max"), ("subscription-1", "subscription-1"))):
        (T / "sala/lane-default").write_text(default + "\n")
        item(first + k, check=f"lane home-nr {word}", next="team-back: move it")        # no row for home-nr: the default decides
        out.append((word, default, tick(1) == [f"a{first + k}"]))
    check(f"5d {tag}: the default lane (its first line) is read both ways, for both lanes", all(o[2] for o in out), out)
    (T / "sala/lane-default").write_text("max\n")
    item(first + 6, check="lane home-nr subscription-2", next="team-back: move it"); item(first + 7, check="lane home-nr team", next="team-back: move it")
    check(f"5d {tag}: a default of one lane does not pass for the other", tick(1) == [] and rd(first + 6)["status"] == rd(first + 7)["status"] == "open")
    drop(first + 6, first + 7)
    (T / "sala/lane-default").unlink()
    item(first + 8, check="lane home-nr max", next="team-back: move it"); item(first + 9, check="lane home-nr subscription-1", next="team-back: move it")
    item(first + 10, check="lane home-nr team", next="team-back: move it")
    check(f"5d {tag}: with no lane-default the fallback is subscription-1, whichever word the check has", sorted(tick(1)) == [f"a{first + 8}", f"a{first + 9}"] and rd(first + 10)["status"] == "open")
    drop(first + 10)
check("5d: no lane-names file now", not NAMES.exists())
lane_pairs("no lane-names file", 80)
lane_defaults("no lane-names file", 92)
# the file as the tool will write it: the current codes, the first ones as their aliases (and, for a file older than the rename, listing the first codes as the codes)
lane_names([{"code": "subscription-1", "display": "Made Up One", "aliases": ["max"]}, {"code": "subscription-2", "display": "Made Up Two", "aliases": ["team"]}, {"code": "api", "display": "Plain", "aliases": []}])
try:
    lane_pairs("lane-names file with aliases", 110)
    lane_defaults("lane-names file with aliases", 122)
    refused("…a refusal names the tool's lanes with their display names", lambda: server._update("a1", check="lane home-x API", sender="home-owner"), "the tool's lanes: subscription-1 (Made Up One), subscription-2 (Made Up Two), api (Plain)")
    lane_names([{"code": "max", "display": "Made Up One", "aliases": []}, {"code": "team", "display": "Made Up Two", "aliases": []}, {"code": "api", "display": "Plain", "aliases": []}])
    lane_pairs("lane-names file of the first codes", 140)
    lane_defaults("lane-names file of the first codes", 152)
finally:
    NAMES.unlink(missing_ok=True)          # the scratch folder goes at the end of the run; the file is gone for the sections after this one at once
check("5d: …the file is gone again", not NAMES.exists())
(T / "sala/lanes.tsv").write_text("home-w\tmax\nhome-x\tapi\n"); (T / "sala/lane-default").write_text("api\n")

# ---- 6. pr_merged against the fake GitHub
item(27, check="pr_merged o/r#7", next="team-back: merge it")
item(28, check="pr_merged o/r#7", next="team-back: merge it too")
F.log.clear()
check("one GET for the two items naming the PR, unmerged: open", tick(1) == [] and len(gets(7)) == 1 and rd(27)["status"] == "open" and st()["github"]["o/r#7"]["merged"] is False, (F.log, st()))
check("within [check] github_minutes no second GET", tick(4) == [] and len(gets(7)) == 1, F.log)
F.merged[7] = True
check("the answer is kept until the cadence comes round", tick(0) == [] and len(gets(7)) == 1)
closed = tick(1)
check("at the cadence: one GET, merged, both items closed with the reason", sorted(closed) == ["a27", "a28"] and len(gets(7)) == 2 and rd(27)["metadata"].get("reason") == "done check passed: pr_merged o/r#7", (closed, F.log, rd(27)["metadata"]))
check("the PR's state is pruned once no open item names it", "o/r#7" not in st()["github"], st())

# ---- 6a. one read for the done check and the other readers of a pull request's state (pr_state.py): the event wait's early read and the step proof's file ask for the same PR inside the pace
F.merged[39] = False; item(80, check="pr_merged o/r#39", next="team-back: merge it"); F.log.clear()
tick(1)
check("6a: the done check's pass reads PR 39 once", len(gets(39)) == 1 and st()["github"]["o/r#39"]["merged"] is False, (F.log, st()))
server._evwait_preread("event", "pr_merged o/r#39")
check("6a: the event wait's early read of the same PR inside the pace makes no GET, and its own memory holds the record the check pass kept",
      len(gets(39)) == 1 and evwaits_svc.EVW_GH.get("o/r#39", {}).get("merged") is False and evwaits_svc.EVW_GH["o/r#39"] == st()["github"]["o/r#39"], (F.log, evwaits_svc.EVW_GH))
proof_gh = {}
with server._gb.tag("step_proof"):
    got = server._pr_merged("o/r#39", clock[0] + 1, proof_gh)
check("6a: …nor does the step proof's read (its own dict gets the record all the same), and the pair it returns is the same", len(gets(39)) == 1 and got == (False, "") and proof_gh["o/r#39"]["merged"] is False, (F.log, proof_gh))
F.closed.add(39); F.merged[39] = False
tick(5)
check("6a: at the cadence one GET again, whichever caller asks first", len(gets(39)) == 2, F.log)
evwaits_svc.EVW_GH.clear()
got = server._pr_merged("o/r#39", clock[0] + 1, evwaits_svc.EVW_GH)
check("6a: a closed-unmerged answer reaches the other reader's dict as `dead` without a second GET (the done check failed the wait)", len(gets(39)) == 2 and got == (False, "") and evwaits_svc.EVW_GH["o/r#39"].get("dead", "").endswith("without being merged"), (F.log, evwaits_svc.EVW_GH))
item(29, check="pr_merged o/r#404", next="team-back: merge it")
F.log.clear()
check("a PR GitHub refuses (404): an error, never a close, logged once", tick(1) == [] and "GitHub refused the read (HTTP 404" in st()["items"]["a29"]["err"] and server._CHECK_LOGGED.get("a29", "").startswith("GitHub refused"), st())
check("…tried again at the cadence, not every pass", tick(4) == [] and len(gets(404)) == 1 and tick(1) == [] and len(gets(404)) == 2, F.log)
F.merged[404] = False; F.down = True; F.log.clear()
tick(5)
check("GitHub down: an error with a backoff of the cadence", "GitHub did not answer" in st()["items"]["a29"]["err"] and st()["github"]["o/r#404"]["back"] == 300.0 and len(gets(404)) == 1, (st(), F.log))
tick(5)
check("…doubling while it stays down", st()["github"]["o/r#404"]["back"] == 600.0 and len(gets(404)) == 2, (st(), F.log))
F.down = False; F.merged[404] = True
check("…and the doubled wait holds: no GET yet", tick(5) == [] and len(gets(404)) == 2, F.log)
check("back up: the next read closes it", tick(5) == ["a29"] and len(gets(404)) == 3 and "a29" not in server._CHECK_LOGGED, (F.log, rd(29)["metadata"]))

# ---- 6b. a pull request closed without being merged: the check can never pass; the wait fails at once, the keeper is told, the item stays open
item(35, check="pr_merged o/r#9", next="team-back: merge it")
told.clear(); F.log.clear()
check("an open PR: not yet, nothing failed", tick(1) == [] and rd(35)["status"] == "open" and "wait_failed" not in rd(35)["metadata"], rd(35)["metadata"])
F.closed.add(9)
tick(5)                                             # the cadence comes round
m35 = rd(35)["metadata"]
check("a PR closed unmerged: the item stays open, its check is gone and the wait is recorded as failed with the reason",
      rd(35)["status"] == "open" and "check" not in m35 and m35.get("wait_failed", {}).get("what") == "check pr_merged o/r#9" and "closed without being merged" in m35["wait_failed"]["why"], m35)
check("the keeper is told once, in one line that says the wait can no longer end and what to give it",
      [(x[0], x[2]) for x in told if x[1] == "a35"] == [("wait", U["home-stew"])] and "can no longer end" in [x[3] for x in told if x[1] == "a35"][0] and "closed without being merged" in [x[3] for x in told if x[1] == "a35"][0], told)
check("get says the wait failed", "wait failed: check pr_merged o/r#9" in _wt_get.stackshot_get("a35"), _wt_get.stackshot_get("a35"))
check("the check pass does not read it again", tick(5) == [] and "a35" not in st()["items"], st())

# ---- 6c. a check met while his decision is open waits (one line, once) and closes the item once the decision is cleared; clear_check takes the check off
import inspect
ASKD = "Decide: x · Recommend: yes · Stakes: z · By: no date"
_saves = []; _orig_save = writes.save
def _spy_save(gid, it, writer="", note="", **kw):
    _saves.append((gid, note)); return _orig_save(gid, it, writer=writer, note=note, **kw)
writes.save = _spy_save
item(62, status="completed", outcome="done", reason="finished")
item(63, check="item_closed a62", needs=["decision"], ask=ASKD, next="home-owner: decide")
item(64, check="item_closed a62", needs=["external"], next="home-owner: wait for them")
told.clear()
closed = tick(1)
waits63 = [n for g, n in _saves if g == "a63"]
check("check met while needs holds decision: the item is not closed, and stays as it was", "a63" not in closed and rd(63)["status"] == "open" and rd(63)["metadata"].get("check") == "item_closed a62"
      and rd(63)["metadata"].get("needs") == ["decision"] and rd(63)["metadata"].get("ask") == ASKD and "outcome" not in rd(63)["metadata"], (closed, rd(63)))
check("…one line records that the check is met and waits for the decision", len(waits63) == 1 and "done check met: item_closed a62" in waits63[0] and "decision" in waits63[0], _saves)
check("…the keeper is not told (nothing closed), the clocks did not move", not [x for x in told if x[1] == "a63"] and rd(63)["updated"] == now0 - 60 and rd(63)["state_updated"] == now0 - 60, (told, rd(63)))
check("another needs (external) keeps today's behaviour: the same check closes it", "a64" in closed and rd(64)["status"] == "completed", (closed, rd(64)))
check("the pass records that it is met", st()["items"]["a63"].get("met") == "item_closed a62" and st()["items"]["a63"]["err"] == "", st())
check("get says the check is met and waits for the decision", "waiting for" in _wt_get.stackshot_get("a63") and "before it closes the item" in _wt_get.stackshot_get("a63"), _wt_get.stackshot_get("a63"))
check("later passes, the decision still open: still open and no second line", tick(3) == [] and rd(63)["status"] == "open" and len([1 for g, n in _saves if g == "a63"]) == 1, [(g, n) for g, n in _saves if g == "a63"])
server._update("a63", clear_needs=True, sender="home-owner")
check("the decision cleared by a write: the item is still open until the pass", rd(63)["status"] == "open" and "needs" not in rd(63)["metadata"], rd(63)["metadata"])
n_before_close = len(_saves)
closed = tick(1)
check("…and the next pass completes it, outcome done, the reason naming the check", closed == ["a63"] and rd(63)["status"] == "completed" and rd(63)["metadata"].get("outcome") == "done"
      and rd(63)["metadata"].get("reason") == "done check passed: item_closed a62", (closed, rd(63)["metadata"]))
check("…with no waiting line at the close, and its record gone from the pass's state", not [n for g, n in _saves[n_before_close:] if g == "a63" and "done check met" in n] and "a63" not in st()["items"], (_saves[n_before_close:], st()))
# a changed check met under the same open decision says so again
item(68, check="item_closed a62", needs=["decision"], ask=ASKD, next="home-owner: decide")
tick(1); n68 = len([1 for g, n in _saves if g == "a68" and "done check met" in n])
server._update("a68", check="unit_active nothing-here.service", sender="home-owner")
server._unit_run = lambda argv: "LoadState=loaded\nActiveState=active\n"
check("a different check met under the same open decision gets its own line", tick(1) == [] and len([1 for g, n in _saves if g == "a68" and "done check met" in n]) == n68 + 1 and "unit_active nothing-here.service" in [n for g, n in _saves if g == "a68"][-1], _saves)
writes.save = _orig_save
server._update("a68", clear_check=True, sender="home-owner"); item(68, status="completed", outcome="dropped", reason="out of the passes")

# clear_check: the flag removes the check, as clear_needs removes needs; check="" is not passed, as needs="" is
item(69, check="item_closed a70", next="x", needs=["team-back"]); item(70)
was69 = rd(69)
out = server._update("a69", clear_check=True, sender="home-owner")
check("clear_check removes the check and nothing else", "check" not in rd(69)["metadata"] and rd(69)["metadata"].get("next") == "x" and rd(69)["metadata"].get("needs") == ["team-back"], rd(69)["metadata"])
check("…the returned item no longer shows a check line", "updated a69" in out and "check:" not in out, out)
check("…and the pass leaves it alone", tick(2) == [] and rd(69)["status"] == "open" and "a69" not in st()["items"], (rd(69), st()))
out = _wt_update.stackshot_update("a69", clear_check=True, sender="home-owner")
check("clear_check on an item with no check is a no-op, not an error", "updated a69" in out and "check" not in rd(69)["metadata"], out)
item(71, check="item_closed a70", next="x", needs=["team-back"])
server._update("a71", next="home-owner: y", check="", sender="home-owner"); server._update("a71", next="home-owner: z", needs="", sender="home-owner")
check('check="" is ignored, as needs="" is: both stay', rd(71)["metadata"].get("check") == "item_closed a70" and rd(71)["metadata"].get("needs") == ["team-back"] and rd(71)["metadata"].get("next", "").endswith("z"), rd(71)["metadata"])
server._update("a71", check="none", sender="home-owner")
check('check="none" still clears it (the old way), as needs="none" does', "check" not in rd(71)["metadata"], rd(71)["metadata"])
item(72, check="item_closed a70", next="x")
server._update("a72", clear_check=True, check="item_closed a62", sender="home-owner")
check("clear_check beside a new check: the new check stands, as clear_needs beside a new needs", rd(72)["metadata"].get("check") == "item_closed a62", rd(72)["metadata"])
check("the update description and the tool's parameters name clear_check", "clear_check=true" in _wt_update._UPDATE_DESC and "clear_check" in inspect.signature(server._update).parameters
      and "clear_check" in inspect.signature(_wt_update.stackshot_update).parameters, _wt_update._UPDATE_DESC[-200:])

# ---- 6d. the waiting line is written once per met check: an error pass or a race keeps the record, a clean "not met" resets it; get shows "met" only while it is true
_saves = []
writes.save = _spy_save
def waits(g): return [n for gg, n in _saves if gg == g and "done check met" in n]
UNITS = ["LoadState=loaded\nActiveState=active\n"]
server._unit_run = lambda argv: UNITS[0]
ACTIVE, INACTIVE, NOANSWER = "LoadState=loaded\nActiveState=active\n", "LoadState=loaded\nActiveState=inactive\n", ""
item(73, check="unit_active w73.service", needs=["decision"], ask=ASKD, next="home-owner: decide")
UNITS[0] = ACTIVE; tick(1)
check("met under an open decision: one waiting line", len(waits("a73")) == 1 and st()["items"]["a73"].get("met") == "unit_active w73.service", (_saves, st()))
UNITS[0] = NOANSWER; tick(1)
check("an error pass keeps the record of the line written", st()["items"]["a73"]["err"] and st()["items"]["a73"].get("met") == "unit_active w73.service", st())
UNITS[0] = ACTIVE; tick(1)
check("…and met again after it: still exactly one line", len(waits("a73")) == 1 and st()["items"]["a73"].get("met") == "unit_active w73.service" and rd(73)["status"] == "open", (_saves, st()))
UNITS[0] = INACTIVE; tick(1)
check("a clean pass that finds it not met resets the record", st()["items"]["a73"]["err"] == "" and "met" not in st()["items"]["a73"], st())
UNITS[0] = ACTIVE; tick(1)
check("…so met again after that writes a second line", len(waits("a73")) == 2, _saves)
item(74, check="unit_active w74.service", needs=["decision"], ask=ASKD, next="home-owner: decide")
UNITS[0] = ACTIVE; tick(1)
def unit_run_editing74(argv):                     # a session's write lands while the check runs
    server._update("a74", next="home-owner: decide, please", sender="home-owner"); server._unit_run = lambda argv: UNITS[0]; return UNITS[0]
server._unit_run = unit_run_editing74
tick(1)
check("a write during the check (a race pass) keeps the record", len(waits("a74")) == 1 and st()["items"]["a74"].get("met") == "unit_active w74.service" and rd(74)["status"] == "open", (_saves, st()))
tick(1)
check("…and the next pass writes no second line", len(waits("a74")) == 1, _saves)
server._update("a74", check="unit_active w74b.service", sender="home-owner")
check("get shows nothing of the old met right after the check was replaced, though the record still holds it",
      "waiting for" not in _wt_get.stackshot_get("a74") and st()["items"]["a74"].get("met") == "unit_active w74.service", (_wt_get.stackshot_get("a74"), st()))
server._update("a74", check="unit_active w74.service", sender="home-owner")
check("get shows it again while the check is the one met and the decision is open", "met, and waiting for" in _wt_get.stackshot_get("a74"), _wt_get.stackshot_get("a74"))
server._update("a74", clear_needs=True, sender="home-owner")
check("…and not once the decision is cleared, before the pass that closes it", "waiting for" not in _wt_get.stackshot_get("a74") and rd(74)["status"] == "open", _wt_get.stackshot_get("a74"))
writes.save = _orig_save
for i in (73, 74): item(i, status="completed", outcome="dropped", reason="out of the passes")

# ---- 7. the descriptions say so
cd = str(getattr(_wt_create.stackshot_create, "description", "") or "")
check("the create and update descriptions carry the check field and the gate", all("check: what closes this item once the work handed to another session is done" in d and "pr_merged <owner>/<repo>#<n>" in d
      and "is refused unless the item carries a check or a wake" in d and "the hand-off's backstop" in d for d in (_wt_update._UPDATE_DESC, cd or _wt_text._CHECK_FORM)), (len(cd), _wt_update._UPDATE_DESC[-300:]))
check("the close form still sits inside the first 2048 characters of the update description", 0 < _wt_text._lead(_wt_update._UPDATE_DESC).find("drops outcome, outcome_text, reason and superseded_by.") < 2048 - 40)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print(("ok" if not fails else "FAILED") + f": check scenario, {len(ran)} checks" + (f", {len(fails)} failed" if fails else "")); sys.stdout.flush(); os._exit(1 if fails else 0)
