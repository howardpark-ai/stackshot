"""Scenario test for the router's `anchor-work` rule — fixture pages and notices, no live
store, no network, no server, no thin call.

A notice of kind anchor from an anchor that carries a `#mention=<text>` filter goes to the agent the page's lead names for the work, without
the thin call's judgment. On the same filtered anchor (`https://x.slack.com/archives/C0000000001#mention=release`, project
`projects/example-docs/website`) two notices (a1b2c4, a1b2c5) are replayed here in their logged shape.

Covers: pages.lead_text / lead_agents / cmd_registry (the registry's `lead_agents` of a sub-page: the agents of its page, top-level page or hub
that its lead names, whole names only, the `## ` sections below the lead left out); both notices pass to example-docs-builder by rule anchor-work
(code, not for Oliver), also a notice that names Oliver (no clamp); an identical repeat within an hour is dropped, another text or the same one an hour later is not; an unfiltered anchor, an anchor listed with and without a filter, a page whose lead names no agent, only the -main agent
or two agents other than -main, an anchor scoped to an item (goes to anchor-item), an anchor of another project, a work agent that is the sender, and a message notice fall through (no
anchor-work); an image-only notice on the filtered anchor is still held by `image`; the live act delivers the pass to the work agent (a front
agent with the mark, a background agent without) and rules the notice.

    tests/run-suite anchor_work        → exit 0 / 1"""
import json, logging, os, pathlib, re, sys, time
SCR = os.path.dirname(os.path.abspath(__file__)); STACK = os.path.dirname(SCR)
import _scratch, _instance
tmp = _scratch.mkdtemp(prefix="anchorwork-"); T = pathlib.Path(tmp)
toml = _instance.apply(pathlib.Path(STACK, "stackshot.example.toml").read_text(encoding="utf-8"))
toml = toml.replace('session_links = "~/.local/state/salamander/fleet"', 'session_links = ""', 1); assert 'session_links = ""' in toml   # never the host's sala store
for key, val in (("repo", tmp), ("store", f"{tmp}/store"), ("markdown", f"{tmp}/board.md"), ("brain", f"{tmp}/brain"),
                 ("state", f"{tmp}/state"), ("secrets", f"{tmp}/secrets"), ("project_touch", f"{tmp}/touch"), ("rules", f"{tmp}/RULES.md"), ("timezone", "Asia/Dubai")):
    toml, n = re.subn(rf'(?m)^{key} = "[^"]*"', f'{key} = "{val}"', toml); assert n == 1, key
toml, n = re.subn(r'(?m)^prefixes = .*$', 'prefixes = ["[work] ", "[home] "]', toml); assert n == 1
(T / "stackshot.toml").write_text(toml, encoding="utf-8")
os.environ.update(STACKSHOT_CONFIG=f"{tmp}/stackshot.toml", STACKSHOT_AUTH="off", STACKSHOT_FLEET_DIR=f"{tmp}/fleet"); os.environ.pop("STACKSHOT_URL", None)
for d in ("store/a", "fleet/a", "state/anchor-hub", "secrets", "touch", "repo", "brain/projects/example-docs", "brain/projects/other"): (T / d).mkdir(parents=True)
NAMES = ("example-docs-main", "example-docs-builder", "example-docs-notes", "example-docs", "home-other")
U = {n: f"00000000-0000-4000-8000-00000000000{i}" for i, n in enumerate(NAMES, 1)}
(T / "fleet/a/machine.json").write_text(json.dumps({"letter": "a", "fleet": "testbox", "claude": "1.0.0"}))
(T / "fleet/a/sessions.json").write_text(json.dumps({u: {"name": n, "machine": "a", "url": "", "seen": "x"} for n, u in U.items()}))
(T / "store/next-id").write_text("10")
(T / "store/a/1.json").write_text(json.dumps({"id": "1", "subject": "[home] release notes", "description": "- A thing\n- Lives here\n- Done when done", "status": "open", "updated": 1.0,
                                              "metadata": {"owner": "example-docs-notes", "mover": "example-docs-notes", "project": "projects/example-docs/scoped"}}))
SLACK = "https://x.slack.com/archives/C0000000001"
OTHER = "https://x.slack.com/archives/C0000000002"
(T / "store/anchors.json").write_text(json.dumps({
    "projects/example-docs/website": [{"url": SLACK + "#mention=release", "items": None, "added": 1, "by": "t"}],
    "projects/example-docs/plain": [{"url": OTHER, "items": None, "added": 1, "by": "t"}],                        # the lead names the work agent, the anchor has no filter
    "projects/example-docs/mixed": [{"url": SLACK + "#mention=release", "items": None, "added": 1, "by": "t"}, {"url": SLACK, "items": None, "added": 1, "by": "t"}],
    "projects/example-docs/nolead": [{"url": SLACK + "#mention=release", "items": None, "added": 1, "by": "t"}],
    "projects/example-docs/onlymain": [{"url": SLACK + "#mention=release", "items": None, "added": 1, "by": "t"}],
    "projects/example-docs/two": [{"url": SLACK + "#mention=release", "items": None, "added": 1, "by": "t"}],
    "projects/example-docs/scoped": [{"url": SLACK + "#mention=release", "items": ["a1"], "added": 1, "by": "t"}],      # a filtered anchor scoped to one item
    "projects/example-docs/news": [{"url": SLACK + "#mention=release", "items": None, "added": 1, "by": "t"}]}))

def page(rel, front, body):
    q = T / "brain" / rel; q.parent.mkdir(parents=True, exist_ok=True); q.write_text("---\n" + front + "\n---\n\n" + body, encoding="utf-8")
HUB = ("type: project\ntitle: Example Docs\ndisplay-name: example-docs\nagents:\n  example-docs-main: the owner's contact for the docs\n  example-docs-builder: builds the docs site on example.com\n"
       "  background:\n    example-docs-notes: drafts release notes\nstatus: active")
page("projects/example-docs.md", HUB, "# Example Docs\n\nThe docs project.\n\n## Current state\n\nstate\n")
SUB = "type: project\ntitle: {t}\nstatus: active"
page("projects/example-docs/website.md", SUB.format(t="Website"),
     "# Website\n\nSub-page of [[projects/example-docs]]. A sub-page with no keeper of its own: `example-docs-main` keeps it; the work is done by the agent `example-docs-builder` (box-a).\n\n"
     "## Summary\n\nThe release-notes agent example-docs-notes is not part of this page's lead.\n")
page("projects/example-docs/plain.md", SUB.format(t="Plain"), "# Plain\n\n`example-docs-main` keeps it; the work is done by `example-docs-builder`.\n")
page("projects/example-docs/scoped.md", SUB.format(t="Scoped"), "# Scoped\n\n`example-docs-main` keeps it; the work is done by `example-docs-builder`.\n")
page("projects/example-docs/mixed.md", SUB.format(t="Mixed"), "# Mixed\n\n`example-docs-main` keeps it; the work is done by `example-docs-builder`.\n")
page("projects/example-docs/nolead.md", SUB.format(t="No lead"), "# No lead\n\nSub-page of the docs project, with nobody named.\n\n## Summary\n\nThe work is done by example-docs-builder (not in the lead).\n")
page("projects/example-docs/onlymain.md", SUB.format(t="Only main"), "# Only main\n\n`example-docs-main` keeps it and does the work; example-docs-main-extra is no agent.\n")
page("projects/example-docs/two.md", SUB.format(t="Two"), "# Two\n\n`example-docs-main` keeps it; the work is done by `example-docs-builder` and `example-docs-notes`.\n")
page("projects/example-docs/news.md", SUB.format(t="News"), "# News\n\n`example-docs-main` keeps it; the work is done by the background agent `example-docs-notes`.\n")
page("projects/other.md", "type: project\ntitle: Other\ndisplay-name: home-other\nstatus: active", "# Other\n\nNothing.\n")

sys.path.insert(0, STACK); logging.disable(logging.INFO)
fails = []; ran = []
def check(name, cond, got=None):
    ran.append(name)
    if not cond: fails.append(name); print(f"FAIL {name}" + (f": {str(got)[:2500]}" if got is not None else ""))

from stackshot.projects import pages as p
p.cmd_registry(quiet=True)
from stackshot.anchors import anchors as a; from stackshot.router import router; from stackshot.router import router_live; from stackshot.router import routing

# ---- 1. the registry's lead_agents
reg = a.registry()
la = lambda k: (reg.get(k) or {}).get("lead_agents")
check("registry: the website's lead names example-docs-main and example-docs-builder, in the order it names them, and nothing from its Summary section",
      la("projects/example-docs/website") == ["example-docs-main", "example-docs-builder"], la("projects/example-docs/website"))
check("registry: a lead that names nobody has no lead_agents; a longer name is not a match", la("projects/example-docs/nolead") is None and la("projects/example-docs/onlymain") == ["example-docs-main"],
      (la("projects/example-docs/nolead"), la("projects/example-docs/onlymain")))
check("registry: the hub's own page (a lead that names no agent) has none", la("projects/example-docs") is None, la("projects/example-docs"))
check("lead_agents: whole names only, case-insensitive, in order of appearance",
      p.lead_agents("Work by EXAMPLE-DOCS-BUILDER, then `a-b`; a-b-c is not it", ["a-b", "example-docs-builder", "zzz"]) == ["example-docs-builder", "a-b"], p.lead_agents("Work by EXAMPLE-DOCS-BUILDER, then `a-b`; a-b-c is not it", ["a-b", "example-docs-builder", "zzz"]))
check("lead_text: no frontmatter and no `## ` section; an unreadable file is ''", p.lead_text(str(T / "brain/projects/example-docs/website.md")).startswith("\n# Website") and "Summary" not in p.lead_text(str(T / "brain/projects/example-docs/website.md"))
      and p.lead_text(str(T / "nope.md")) == "")

# ---- 2. the rule on the notices as the routing log has them (a1b2c4, a1b2c5)
cx = router.Context()
ROOT = "projects/example-docs"
def notice(i, key="projects/example-docs/website", text="x", who="Alex Example", ts=1792000001.49, anchor="slack:C0000000001", kind="anchor", **kw):
    return {"id": i, "ts": ts, "kind": kind, "to": U["example-docs"], "label": "Slack #announcement", "who": who, "text": text,
            "url": "https://x.slack.com/archives/C0000000001/p1792000000123456", "target": "project-wide", "pilot": True, "anchor": anchor, **kw}
T_a = "Example library 2.0.0 has been released. 2.0.0 is the first major release in a year."
T_b = "Example library 2.0.1 has been released. 2.0.1 is a bug-fix release."
rule = lambda n, key="projects/example-docs/website", peers=(), c=None: router.code_rule(key, n, ROOT, c or cx, list(peers))
for nid, txt in (("a1b2c4", T_a), ("a1b2c5", T_b)):
    ln = rule(notice(nid, text=txt))
    check(f"{nid}: passed to example-docs-builder by the code rule anchor-work",
          ln and (ln["source"], ln["rule"], ln["ruling"], ln["target"], ln["for_owner"], ln["id"], ln["key"], ln["project"]) == ("code", "anchor-work", "passed", "example-docs-builder", False, nid, "projects/example-docs/website", ROOT), ln)
    check(f"{nid}: the reason names the filter and the work agent", ln and "(release)" in ln["reason"] and "example-docs-builder" in ln["reason"], ln and ln["reason"])
ln = rule(notice("f1", text="[for Oliver] 2.0.1 is out, needs: decision on the notes"))
check("a notice that names Oliver passes to the work agent too (no clamp), the agent judges it", ln and (ln["rule"], ln["ruling"], ln["target"]) == ("anchor-work", "passed", "example-docs-builder"), ln)
ln = rule(notice("f2", text=T_a, anchor="slack:C0000000001", target="for example-docs-main"))
check("a target of `for <agent>` on the notice makes no difference to a filtered anchor", ln and ln["rule"] == "anchor-work" and ln["target"] == "example-docs-builder", ln)

# repeat within an hour (as anchor-builder), a different text or an hour later is not a repeat
first = notice("r1", text=T_a, ts=1000.0)
ln = rule(notice("r2", text=T_a, ts=1100.0), peers=[first])
check("an identical repeat within an hour is dropped", ln and (ln["rule"], ln["ruling"], ln["target"]) == ("repeat", "dropped", "") and "r1" in ln["reason"], ln)
ln = rule(notice("r3", text=T_b, ts=1100.0), peers=[first])
check("another text on the same anchor is not a repeat", ln and ln["rule"] == "anchor-work", ln)
ln = rule(notice("r4", text=T_a, ts=1000.0 + router.REPEAT_WINDOW + 5), peers=[first])
check("the same text more than an hour later is not a repeat", ln and ln["rule"] == "anchor-work", ln)

# ---- 3. falls through
fell = lambda name, ln: check(name, ln is None or ln["rule"] != "anchor-work", ln)
fell("an unfiltered anchor (its page's lead names the work agent) is not anchor-work", rule(notice("u1", key="projects/example-docs/plain", text=T_a, anchor="slack:C0000000002"), key="projects/example-docs/plain"))
fell("an anchor listed once with a filter and once without is not a filtered one", rule(notice("u2", text=T_a), key="projects/example-docs/mixed"))
ln = rule(notice("u13", text=T_a, target="for example-docs-notes"), key="projects/example-docs/scoped")
check("a filtered anchor scoped to an item is not anchor-work: it goes to anchor-item and the item's owner", ln and (ln["rule"], ln["ruling"], ln["target"], ln["item"]) == ("anchor-item", "passed", "example-docs-notes", "a1"), ln)
fell("a page whose lead names no agent falls through", rule(notice("u3", text=T_a), key="projects/example-docs/nolead"))
fell("a page whose lead names only the -main agent falls through", rule(notice("u4", text=T_a), key="projects/example-docs/onlymain"))
fell("a page whose lead names two agents other than -main falls through", rule(notice("u5", text=T_a), key="projects/example-docs/two"))
fell("a notice whose anchor is not one the project lists (another project's channel) falls through", rule(notice("u6", text=T_a, anchor="slack:C0000000009")))
fell("a notice from the page of another project (no anchors of its own) falls through", router.code_rule("projects/other", notice("u7", text=T_a), "projects/other", cx, []))
fell("a work agent that sent the notice itself falls through", rule(notice("u8", text=T_a, who="example-docs-builder")))
fell("a message notice is not anchor-work", rule(notice("u9", kind="message", text=T_a, anchor="")))
fell("an anchor notice with no anchor id is not anchor-work", rule(notice("u10", text=T_a, anchor="")))
ln = rule(notice("u11", text=T_a), key="projects/example-docs/news")
check("a lead that names one background agent other than -main passes to it (front or background)", ln and (ln["rule"], ln["target"]) == ("anchor-work", "example-docs-notes"), ln)

# an old registry with no lead_agents yet falls through
old = router.Context(); old.reg = {k: {x: y for x, y in e.items() if x != "lead_agents"} for k, e in old.reg.items()}
fell("a registry that has no lead_agents (not rebuilt yet) falls through to today's rules", rule(notice("u12", text=T_a), c=old))

# ---- 4. an image-only notice on the filtered anchor stays held by `image`
ln = rule(notice("i1", text="[files: image.png]"))
check("an image-only notice on a filtered anchor is held by image, not passed", ln and (ln["rule"], ln["ruling"], ln["target"]) == ("image", "held", ""), ln)

# ---- 5. the live act delivers the pass to the work agent and rules the notice
sent = []
router_live._HOOKS["deliver"] = lambda target, text: (sent.append((target, text)), "delivered → " + target)[1]
router_live._HOOKS["is_front"] = None
def live(key, nid, txt, anchor="slack:C0000000001"):
    rec = routing.record(key, kind="anchor", to=U["example-docs"], label="Slack #announcement", who="Alex Example", text=txt, pilot=True, anchor=anchor,
                         url="https://x.slack.com/archives/C0000000001/p1792000000123456", target="project-wide")
    n = next(x for x in routing.read(key) if x["id"] == rec["id"] ) if isinstance(rec, dict) and rec.get("id") else routing.read(key)[-1]
    c = router.Context(); ln = router.code_rule(key, n, ROOT, c, [])
    return n, ln, router_live._act(n, key, ROOT, ln, c, {})
n, ln, res = live("projects/example-docs/website", "l1", T_b)
check("live: the filtered anchor's notice is delivered to example-docs-builder (a front agent: marked, as every delivery to one) and ruled passed by anchor-work",
      ln["rule"] == "anchor-work" and res.get("status") == "ruled" and sent and sent[-1][0] == "example-docs-builder" and res.get("marked") is True
      and [x for x in routing.read("projects/example-docs/website") if x["id"] == n["id"]][-1].get("ruling") == "passed", (ln, res, sent[-1:]))
n, ln, res = live("projects/example-docs/news", "l2", T_b)
check("live: a background work agent gets it unmarked", ln["rule"] == "anchor-work" and res.get("status") == "ruled" and sent[-1][0] == "example-docs-notes"
      and res.get("marked") is False, (ln, res, sent[-1:]))

print(f"{len(ran) - len(fails)}/{len(ran)} checks passed")
sys.exit(1 if fails else 0)
