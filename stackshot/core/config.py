"""config.py — the instance config of this stackshot: every path, identity, rule and label that belongs to the setup rather
than to the code). The instance's file lives outside the code: it is found, in
order, at $STACKSHOT_CONFIG, ~/.config/stackshot/stackshot.toml, a stackshot.toml next to this file, and last the shipped
stackshot.example.toml next to this file — the defaults, enough for a client box that only needs [client] and the secrets
dir, and for the tests, which patch what they need. Stdlib only (tomllib), so the pane gate on every box reads it.

    from config import CFG, get, path, state, secrets
    get("instance", "owner")            → "the owner"
    path("paths", "store")              → Path, ~ expanded
    state("site", "favicon.svg")        → <paths.state>/site/favicon.svg
    secrets("oauth.env")                → <paths.secrets>/oauth.env

CLI (for shell scripts):  python3 config.py get instance.owner | path paths.store | state anchor-hub | secrets oauth.env
                          python3 config.py file   → the config file in use
                          python3 config.py check  → exit 0 when the file names no removed mode; otherwise the refusal line(s), exit 1
                                                     (importing this module does the same: see REMOVED)

Live reload: a long-running process (the server, anchor-hub) calls reload() on SIGHUP, which systemd sends on
`systemctl --user reload` when stackshot-reload.path sees the file change. A valid file replaces CFG at once and every reader
sees it at its next get(); a broken one is logged and the running config kept. The keys of RESTART_ONLY keep their running
value until the next restart. So a reader must never copy a setting into a module constant: read it where it is used.
"""
from __future__ import annotations
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]

import os
import re
import sys
import tomllib
from pathlib import Path
from typing import Any
from stackshot import paths as _paths

HERE = _paths.ROOT      # the checkout: stackshot.example.toml and a stackshot.toml sit at its root
EXAMPLE = HERE / "stackshot.example.toml"


def _find() -> Path:
    env = os.environ.get("STACKSHOT_CONFIG") or os.environ.get("BOARD_MCP_CONFIG")
    if env:
        return Path(os.path.expanduser(env))
    for p in (Path(os.path.expanduser("~/.config/stackshot/stackshot.toml")), HERE / "stackshot.toml", EXAMPLE):
        if p.is_file():
            return p
    return EXAMPLE


PATH = _find()


def load(p: Path = PATH) -> dict[str, Any]:
    with open(p, "rb") as f:
        return tomllib.load(f)


CFG: dict[str, Any] = load()


def tz():
    """The instance's timezone (instance.timezone, default UTC as in the example): every time the board, the hub or a notice prints."""
    import zoneinfo
    return zoneinfo.ZoneInfo(str(get("instance", "timezone") or "UTC"))


def tz_abbr(when: Any = None) -> str:
    """The instance timezone's abbreviation (strftime %Z) at `when` (a datetime; a naive one is read in the instance zone), or
    now: the zone's abbreviation ("UTC" for UTC, "CET" for a zone that has one), the zone's own offset label where it has no abbreviation."""
    import datetime
    z = tz()
    when = datetime.datetime.now(z) if when is None else when.replace(tzinfo=z) if when.tzinfo is None else when.astimezone(z)
    return when.strftime("%Z") or str(z)


def tz_labels() -> list[str]:
    """Every abbreviation (strftime %Z) the instance timezone shows over a year (["CET", "CEST"]; ["UTC"]; ["+04"] for a zone with no abbreviation), for a text
    that may name the zone after a clock time ("at 03:00 CET")."""
    import datetime
    z = tz()
    out: list[str] = []
    for month in (1, 7):
        lab = datetime.datetime(2026, month, 1, 12, tzinfo=z).strftime("%Z") or str(z)
        if lab not in out:
            out.append(lab)
    return out


def get(*keys: str, default: Any = None, cfg: dict[str, Any] | None = None) -> Any:
    d: Any = CFG if cfg is None else cfg     # CFG read once: a reload in between never mixes two files in one answer
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d


def path(*keys: str, default: str | None = None) -> Path:
    v = get(*keys, default=default)
    if v is None:
        raise KeyError(".".join(keys))
    return Path(os.path.expanduser(str(v)))


def paths(*keys: str) -> list[Path]:
    """A config key holding a list of paths (a bare string counts as a one-item list), each `~`-expanded; absent or empty = []."""
    v = get(*keys)
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return []
    return [Path(os.path.expanduser(x)) for x in v if isinstance(x, str) and x.strip()]


def state(*parts: str) -> Path:
    return path("paths", "state").joinpath(*parts)


def secrets(*parts: str) -> Path:
    return path("paths", "secrets").joinpath(*parts)


def page_dirs() -> list[str]:
    """[pages] dirs: the sub-directories of the pages checkout (paths.brain) that hold project pages, in order; a bare slug
    names a page in the FIRST one. Default ["projects"]; an instance with more lists them (the example file)."""
    v = get("pages", "dirs")
    if isinstance(v, str):
        v = [v]
    out = [str(d).strip().strip("/") for d in (v or []) if str(d).strip().strip("/")]
    return out or ["projects"]


def page_dirs_re() -> str:
    """The page dirs as one non-capturing regex alternation, e.g. (?:projects|infra)."""
    import re
    return "(?:" + "|".join(re.escape(d) for d in page_dirs()) + ")"


def gbrain_bin() -> str:
    """[gbrain] bin: the gbrain command line (rename_page.py, page_debt.GbrainIO, the router's timeline notes). "gbrain" (a name found on PATH)
    by default; a path may start with ~. Read at import by rename_page.py: a change takes a restart. Only a "gbrain" flavor of pages uses it."""
    v = str(get("gbrain", "bin") or "").strip()
    return os.path.expanduser(v) if v else "gbrain"


def page_flavor() -> str:
    """[pages] flavor: how a session is told to update its page. "gbrain" = through gbrain's tools (add_timeline_entry,
    get_page/edit_page/put_page); "plain" (default) = edit the markdown file in the pages checkout, commit and push."""
    v = str(get("pages", "flavor") or "plain").strip().lower()
    return v if v in ("plain", "gbrain") else "plain"


def ask_leaves_on() -> bool:
    """[ask] leaves: true (the default) lets the server take an ask off the owner's move when its author's write is, whole, one plain sentence saying it is wrong (ask_leaves.py); a dropped dependency only reminds its author. false = never removes: the
    reminder and the ask-time check on the owner's notes still show, nothing is taken off his move."""
    return get("ask", "leaves", default=True) is not False


def ask_refuse_after() -> str:
    """[ask] refuse_after: the date (YYYY-MM-DD in the instance timezone) from which a needs=decision item without an ask
    line is refused rather than nagged. "" (the default) = never refuse, nag only. A value
    that is not a date reads as "" (nag)."""
    import datetime
    v = get("ask", "refuse_after")
    if not v:
        return ""
    try:
        return datetime.date.fromisoformat(str(v).strip()).isoformat()
    except ValueError:
        return ""


def board_check_mode() -> str:
    """[board_check] mode: the end-of-turn board check (pages.py check). "block" = a turn that
    did real work while its session owns open items it did not touch is asked once, at its Stop, to update or confirm them or
    to say `Board: no change, <reason>`; "note" = the same question kept for the next prompt instead of holding the turn (the later phase); "off" (the default) = never. Any other value reads as "off"."""
    v = str(get("board_check", "mode") or "off").strip().lower()
    return v if v in ("off", "block", "note") else "off"



# The temporary-directory prefix of the router's own `claude -p` call (router.run_call; the page-debt call shares it). The
# puller (puller.sessions) skips a registry record that lives in such a directory, so the call is never a client session.
ROUTER_CWD_PREFIX = "stackshot-router-"

AUDIT_AGENT = "my-audit"
AUDIT_PROJECT = "demo/board"
AUDIT_AT = "05:00"


def audit_enabled() -> bool:
    """[audit] enabled: the daily board audit (audit.py). true = install.sh installs its timer and
    the server answers POST /audit/now with a cue to [audit] agent; false (the default) = no timer, and a cue is refused (404)."""
    v = get("audit", "enabled")
    return v is True or str(v).strip().lower() in ("true", "1", "yes")


def audit_agent() -> str:
    """[audit] agent: the Claude Code session that runs the audit and writes its run record; a cue is pushed to it.
    Default "my-audit"."""
    return str(get("audit", "agent") or "").strip() or AUDIT_AGENT


def audit_project() -> str:
    """[audit] project: the project sala's Agents tab files the audit timer under (<scope>/<project>; install.sh puts it in the unit's X-Project line). Default "demo/board"."""
    return str(get("audit", "project") or "").strip() or AUDIT_PROJECT


def audit_at() -> list[str]:
    """[audit] at: the times of day of the scheduled audit, each "HH:MM" in the [instance] timezone, sorted and without repeats (the timer's
    OnCalendar lines and audit.next_run). The key takes one "HH:MM" string (a run a day, as it always did) or a list of them (a run at each
    time). An entry that is not a time of day is left out; with none left, the default ["05:00"]."""
    v = get("audit", "at")
    out = set()
    for x in (v if isinstance(v, (list, tuple)) else [v]):
        m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", str(x or "").strip())
        if m:
            out.add(f"{int(m.group(1)):02d}:{m.group(2)}")
    return sorted(out) or [AUDIT_AT]


AUDIT_MODES = ("script", "agent")
AUDIT_ORPHAN_MODES = ("apply", "report", "off")
AUDIT_WAIT_END_MODES = ("fix", "ask", "off")
AUDIT_WAIT_END_SETTLE_MINUTES = 60.0      # an item last written less than this long ago is left to its mover before the wait-end rule fixes anything (wait_end.py)
AUDIT_MAX_CALLS = 40
AUDIT_MAX_MINUTES = 100
AUDIT_MAX_MINUTES_CEIL = 110      # the unit's TimeoutStartSec is 2 h; a longer setting reads as this
AUDIT_THRESHOLD = 5
AUDIT_REMIND_HOURS = 6.0               # a ten-minute finding nobody answered is sent again this long after its last send (audit_run.split_sent)
AUDIT_FRONT_STEP_MOVE_HOURS = 3.0      # a front agent's step that stays stuck-elsewhere this long moves to the item's mover (front_step.py)
AUDIT_BUILDER = "my-engineer"
AUDIT_MAIN = "my-main"
REPORT_TO = "projects/example"        # the stand-in page the audit's summary and a release's report go to until an instance names its own


def audit_mode() -> str:
    """[audit] mode: who runs the audit. "script" (the default) = audit_run.py reads the board in code and makes one `claude -p` call per suspect item; "agent" = the old way,
    one cue line pushed to the audit agent ([audit] agent). Switching back to "agent" is the rollback; a value that is neither reads as the default."""
    v = str(get("audit", "mode") or "").strip().lower()
    return v if v in AUDIT_MODES else "script"


def _audit_int(key: str, default: int, low: int = 0) -> int:
    v = get("audit", key)
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return n if isinstance(v, (int, str)) and not isinstance(v, bool) and n >= low else default


def audit_max_calls() -> int:
    """[audit] max_calls: the most model calls one script run makes (one per suspect item, one at a time); the suspects past it wait for the next run. Default 40; 0 = no call."""
    return _audit_int("max_calls", AUDIT_MAX_CALLS)


def audit_max_minutes() -> int:
    """[audit] max_minutes: the wall-clock a script run may spend on model calls; once this many minutes have passed since the run started, no new call is begun (the suspects left wait for the
    next run) and the record says so. Default 100, kept under the audit unit's 2 h TimeoutStartSec: a value above 110 reads as 110, one below 1 as the default."""
    return min(_audit_int("max_minutes", AUDIT_MAX_MINUTES, 1), AUDIT_MAX_MINUTES_CEIL)


def audit_threshold() -> int:
    """[audit] threshold: a run that finds at least this many findings of one check sends the builder one message naming the check and the items. Default 5; a value below 1 reads as the default."""
    return _audit_int("threshold", AUDIT_THRESHOLD, 1)


def audit_front_step_move_hours() -> float:
    """[audit] front_step_move_hours: how many hours a step held by a front agent (or a retired session) may stay the first open step of an item another session moves, with the stuck-elsewhere finding up, before the
    ten-minute filing pass rewords it to the item's mover (front_step.py). Default 3; 0 = never moves one (the clocks are not kept either). A number (an integer or a decimal); anything else, a negative number or a boolean reads as the default."""
    v = get("audit", "front_step_move_hours")
    if isinstance(v, bool) or v is None or v == "":
        return AUDIT_FRONT_STEP_MOVE_HOURS
    try:
        n = float(v)
    except (TypeError, ValueError):
        return AUDIT_FRONT_STEP_MOVE_HOURS
    return n if n >= 0 and n == n and n != float("inf") else AUDIT_FRONT_STEP_MOVE_HOURS


def audit_remind_hours() -> float:
    """[audit] remind_hours: how many hours a finding of the ten-minute passes that its item has not answered (no write since) waits before it is sent again, in words that mark it as a later try, up to
    audit_run.REMIND_TRIES sends and then once to the project's builder as unmoved. Default 6; 0 = once only, as before. A number; anything else, a negative number or a boolean reads as the default."""
    v = get("audit", "remind_hours")
    if isinstance(v, bool) or v is None or v == "":
        return AUDIT_REMIND_HOURS
    try:
        n = float(v)
    except (TypeError, ValueError):
        return AUDIT_REMIND_HOURS
    return n if n >= 0 and n == n and n != float("inf") else AUDIT_REMIND_HOURS


def audit_wait_end() -> str:
    """[audit] wait_end: what the ten-minute filing pass does with an open item whose next line waits for something nothing tells the item has happened (wait_end.py): "fix" (the default) sets the wait the
    line names where the server can (after, an event wait, an anchor wait, a step proof) and asks the mover about the rest, "ask" only asks the mover, "off" makes no such check. Anything else reads as the default."""
    v = str(get("audit", "wait_end") or "").strip().lower()
    return v if v in AUDIT_WAIT_END_MODES else "fix"


def audit_wait_end_settle_minutes() -> float:
    """[audit] wait_end_settle_minutes: minutes since an item's last write before the wait-end rule fixes anything on it (a mover still at work on its next is left alone). Default 60; 0 = no wait. A number;
    anything else, a negative number or a boolean reads as the default."""
    v = get("audit", "wait_end_settle_minutes")
    if isinstance(v, bool) or v is None or v == "":
        return AUDIT_WAIT_END_SETTLE_MINUTES
    try:
        n = float(v)
    except (TypeError, ValueError):
        return AUDIT_WAIT_END_SETTLE_MINUTES
    return n if n >= 0 and n == n and n != float("inf") else AUDIT_WAIT_END_SETTLE_MINUTES


def audit_orphan_handover() -> str:
    """[audit] orphan_handover: what the audit does with an open item whose mover is gone (successor.py): "report" (the default for the first week of use) only lists it, "apply" hands it to the closest live agent, "off" makes no check.
    A value that is none of these reads as the default."""
    v = str(get("audit", "orphan_handover") or "").strip().lower()
    return v if v in AUDIT_ORPHAN_MODES else "report"


def registry_audit_send() -> bool:
    """[registry_audit] send: whether the daily run sends the project registry check's findings (tools/registry_report.py) to the agents they are for, one message per agent a day. False (the default, and the
    reading of any value that is not the boolean true): the findings are on the run record and `audit.py registry` prints them, nobody is messaged."""
    return get("registry_audit", "send") is True


def audit_builder() -> str:
    """[audit] builder: the session a tripped threshold, and an unmoved finding of a project with no builder of its own, is sent to. Default "my-engineer"."""
    return str(get("audit", "builder") or "").strip() or AUDIT_BUILDER


def audit_main() -> str:
    """[audit] main: the -main agent that receives the findings addressed to the owner (marked `[for <owner>]`) and the run's summary. Default "my-main"."""
    return str(get("audit", "main") or "").strip() or AUDIT_MAIN


_REPORT_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*")


def _report_slug(section: str, key: str) -> str:
    """The page key (or session name) set at [section] key, or REPORT_TO when the key is absent, empty or not shaped like one (letters, digits, dots, hyphens and underscores, "/" between the parts)."""
    v = get(section, key)
    v = v.strip() if isinstance(v, str) else ""
    return v if _REPORT_SLUG.fullmatch(v) else REPORT_TO


def audit_summary_to() -> str:
    """[audit] summary_to: the page key (or session name) the summary of each audit run is sent to (audit_run). Default "projects/example", the stand-in; a value that is not
    a page key or session name reads as the default (notes() says so)."""
    return _report_slug("audit", "summary_to")


def release_report_to() -> str:
    """[release] report_to: the page key (or session name) release.sh sends its report of each release to (green or red, the PR, the commit, what was restarted), and names in the line it prints when
    a release starts. Default "projects/example", the stand-in; a value that is not a page key or session name reads as the default (notes() says so)."""
    return _report_slug("release", "report_to")


def report_notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """Lines for a [audit] summary_to or [release] report_to that is set and cannot be used (see _report_slug): the default stands in its place, so the reports would go to the stand-in page."""
    out: list[str] = []
    for section, key in (("audit", "summary_to"), ("release", "report_to")):
        v = get(section, key, cfg=cfg)
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        if not isinstance(v, str) or not _REPORT_SLUG.fullmatch(v.strip()):
            out.append(f"[{section}] {key} = {v!r} is not a page key or session name (letters, digits, \".\", \"-\" and \"_\", with \"/\" between the parts), so {REPORT_TO} is used: set a page key such as \"projects/example-reports\"")
    return out


def audit_model() -> str:
    """[audit] model: the model of the script's per-suspect calls; "" (the default) = the [router] model."""
    return str(get("audit", "model") or "").strip()


def audit_lane() -> str:
    """[audit] lane: the sala lane the script's per-suspect `claude -p` calls run on (`salamander lane exec <lane> -- claude …`, for example "bedrock"); "" (the default) = the [router]
    command as it is, the lane every other router call uses. Only the audit's calls take it. A value that is not a lane name (lowercase letters, digits and hyphens) reads as the default."""
    import re
    v = str(get("audit", "lane") or "").strip()
    return v if re.fullmatch(r"[a-z][a-z0-9-]*", v) else ""


AUDIT_PATTERN_REVIEWS = ("off", "shadow")


def audit_pattern_review() -> str:
    """[audit] pattern_review: the pattern review, the last stage of a model run (audit_run.pattern_stage): it reads the findings the audits made since the review before it, groups the repeats by kind, agent and
    project, and makes ONE model call (on the audit's lane and model, inside max_minutes and max_calls) that drafts one guardrail per pattern. "shadow" (the default) = the drafts are logged on the run record and
    named in the summary line, and nothing is sent or opened; "off" = no review, no call, and no findings log is kept. A value that is neither reads as the default."""
    v = str(get("audit", "pattern_review") or "").strip().lower()
    return v if v in AUDIT_PATTERN_REVIEWS else "shadow"


WAIT_GUARD_MAX_CALLS = 30         # model calls per rolling hour
WAIT_GUARD_TIMEOUT = 30.0         # seconds one call may take before the write goes through unjudged
WAIT_GUARD_REASON_MIN = 15        # characters a wait_reason needs


def wait_guard_on() -> bool:
    """[wait_guard] enabled (default true): the check on a wait a session sets on its own item (self_wait.py). false = no refusal for a missing reason and no model call. Live."""
    v = get("wait_guard", "enabled")
    return True if v is None else (v not in (False, 0) and str(v).strip().lower() not in ("false", "no", "off", "0"))


def wait_guard_max_calls() -> int:
    """[wait_guard] max_calls: the most model calls in any rolling hour; a write past it goes through unjudged and is logged. Default 30; 0 = no call (the missing-reason refusal still applies)."""
    v = get("wait_guard", "max_calls")
    try:
        n = int(v)
    except (TypeError, ValueError):
        return WAIT_GUARD_MAX_CALLS
    return n if isinstance(v, (int, str)) and not isinstance(v, bool) and n >= 0 else WAIT_GUARD_MAX_CALLS


def wait_guard_timeout() -> float:
    """[wait_guard] timeout_seconds: how long one call may take before the write goes through unjudged. Default 30; below 1 reads as the default."""
    try:
        v = float(get("wait_guard", "timeout_seconds"))
    except (TypeError, ValueError):
        return WAIT_GUARD_TIMEOUT
    return v if v >= 1 else WAIT_GUARD_TIMEOUT


def wait_guard_model() -> str:
    """[wait_guard] model: the model of the call; "" (the default) = the [router] model."""
    return str(get("wait_guard", "model") or "").strip()


FRESHNESS_DAYS = {"call_days": 1.0, "agent_days": 1.0, "external_days": 3.0}


def freshness_days() -> dict[str, float]:
    """[freshness] call_days · agent_days · external_days: how long an active open item may go unconfirmed in its lane
    (your call · on agent · on others) before it reads stale. Defaults 1, 1 and 3; a value that is not a positive
    number keeps its default."""
    out = dict(FRESHNESS_DAYS)
    for k in out:
        try:
            v = float(get("freshness", k))
            if v > 0:
                out[k] = v
        except (TypeError, ValueError):
            pass
    return out


def fleet_dir() -> Path:
    """Where every reader finds <letter>/{machine,sessions}.json: the view the server materialises from its own clients
    (clients.py, <state>/clients/fleet); STACKSHOT_FLEET_DIR points the readers elsewhere (tests)."""
    if os.environ.get("STACKSHOT_FLEET_DIR"):
        return Path(os.environ["STACKSHOT_FLEET_DIR"])
    return state("clients", "fleet")


def fleet_tool() -> str:
    """[fleet] tool_name: the name the prose gives the fleet tool that relaunches panes and keeps the session view ("the board
    shows … (<name> runs it)", "open this session in <name>"). "" (the default) = "the fleet tool": stackshot names no tool of
    its own and runs with none installed."""
    return str(get("fleet", "tool_name") or "").strip()


def owner() -> str:
    """[instance] owner: how the prose names the person this board is for ("the owner" when the key is missing; notes() says so at the start)."""
    return str(get("instance", "owner") or "").strip() or "the owner"


OWNER_KIND = "owner"          # the generic word for the owner's mover kind (the kind the code uses inside, and what [items_api] owner_mover_kind = "owner" emits)


def owner_mover_kind() -> str:
    """The `mover.kind` the items API emits for an item that is the owner's move: [items_api] owner_mover_kind. "legacy" (the default) is a legacy owner label that stays supported: the
    owner's first name in lower case ([instance] owner; "owner" when the instance names no one), the word a reader of the API may match exactly; "owner" is the generic word."""
    if str(get("items_api", "owner_mover_kind", default="legacy") or "").strip().lower() == OWNER_KIND:
        return OWNER_KIND
    name = owner().lower()
    words = re.findall(r"[^\W_]+", name) if name != "the owner" else []      # the placeholder names no one
    return words[0] if words else OWNER_KIND


def owner_shell_mode() -> str:
    """Where the owner runs the commands of a board step ([steps] owner_shell): "powershell" (also written pwsh), "sala-shell" (also sala_shell, salashell), or "" for anything else (no place is asked for)."""
    v = str(get("steps", "owner_shell", default="") or "").strip().lower()
    return "powershell" if v in ("powershell", "pwsh") else "sala-shell" if v in ("sala-shell", "sala_shell", "salashell") else ""


def owner_aliases() -> list[str]:
    """[instance] owner_aliases: the other names a session may open a line of next with for the owner's step (the owner's initials, a name in another language); [] by default.
    The name `you` is always one (a line `you: …` is the owner's) and is not listed here."""
    v = get("instance", "owner_aliases", default=[])
    if not isinstance(v, list):
        return []
    out: list[str] = []
    for a in v:
        a = str(a).strip()
        if a and a != owner() and a not in out and a.lower() != "you":
            out.append(a)
    return out


def owner_names() -> list[str]:
    """The owner's name and every alias, the name first; with no [instance] owner set, only the aliases."""
    own = owner()
    return ([] if own == "the owner" else [own]) + owner_aliases()


def owner_openers() -> list[str]:
    """What a line of next may open with, as the tool text lists it: the aliases with `you` after the first one (`<alias>`, `you`, `<alias>`), or just `you` when none is set."""
    al = owner_aliases()
    return al[:1] + ["you"] + al[1:]


def owner_opener_rx(to: bool = True):
    """A compiled regex for a who-takes-it opener of a line of next that names the owner: `<name>:` (name, alias or `you`, any case for `you`), and with `to` also `<name> to …` for the names
    (never `the owner's`, `ACME-1` or "the owner approved …"). Cached per set of names, so a reload is read at once."""
    return _opener_rx(tuple(owner_names()), to)


_OPENERS: dict[tuple[tuple[str, ...], bool], Any] = {}


def _opener_rx(names: tuple[str, ...], to: bool):
    key = (names, to)
    if key not in _OPENERS:
        alt = "|".join(re.escape(n) for n in names)
        colon = rf"(?:(?:{alt})|[Yy]ou)\s*:" if alt else r"[Yy]ou\s*:"
        pat = rf"^(?:{colon}" + (rf"|(?:{alt})\s+to\b" if alt else "") + ")"
        _OPENERS[key] = re.compile(pat)
    return _OPENERS[key]


# ---------------------------------------------------------------------------------------------------------------- [keywords]: the words of another language
# The matchers that read free text (a step, a notice, an owner's answer) ship with English words only. A language the instance writes in adds its own words under
# [keywords.<feature>] in stackshot.toml; each list ADDS to the English defaults, and a missing section or key is an empty list (the English behavior, exactly).
# A "words" key holds literal words or phrases (matched as written, case-insensitive for scripts that have case; a space inside a phrase stands for any run of white
# space); a "patterns" key holds regular expressions (Python `re` syntax, matched case-insensitively), for a construct that words alone cannot spell.
# KEYWORDS is the one list of the keys: the example file and the docs/configuration*.md pages document each, and notes() names a key that is not here or a value that is not a list of strings.
KEYWORDS: dict[str, dict[str, tuple[str, str]]] = {
    "step_commands": {
        "shell_names": ("words", "other-language names of a shell (the English ones are PowerShell, pwsh, WSL, terminal, shell, console): a text that names one asks the owner to run something there"),
        "windows_words": ("words", "other-language names of Windows or PowerShell: a command with one of them says where it runs"),
        "run_commands": ("words", "other-language imperative phrases that ask the owner to run, type or paste something (run it, type it, paste it)"),
        "after_command": ("words", "words that right after a command's closing backtick make it a command for the owner to run (the verb that follows its object; a particle may be part of the phrase)"),
        "subject_markers": ("words", "the particles that mark a subject right before a backticked command: a session named as the subject runs it, not the owner"),
        "pointer_patterns": ("patterns", "other-language regular expressions for a step that points elsewhere (\"see the description\", \"see below\")"),
        "pane_cues": ("words", "other-language run cues that may stand before a pane-form `! command` (the English ones are type, run, enter, execute, paste)"),
    },
    "router": {
        "decision": ("words", "other-language words for a decision: a notice with one needs the owner (weak signal)"),
        "urgent": ("words", "other-language words for urgent: a notice with one passes the quiet hours"),
    },
    "model_guards": {
        "wait_words": ("words", "other-language words that say an item waits (waiting, wait for): a next line with one reads as a wait"),
        "overnight_words": ("words", "other-language words for overnight: a doing item whose next line says so reads as a wait"),
        "defer_after_id": ("words", "other-language phrases that follow a board id and defer on it (closes, is done, after, until, before)"),
    },
    "dates": {
        "month_suffix": ("words", "the word written right after a month number in a month-and-day date (\"<month number> <this word> <day number> <day_suffix word>\")"),
        "day_suffix": ("words", "the word written right after a day-of-month number (and after a number of days)"),
        "week_suffix": ("words", "the word written right after a number of weeks"),
        "later_words": ("words", "the words after a number of days or weeks that mean \"from now\""),
        "tomorrow": ("words", "other-language words for tomorrow"),
        "day_after_tomorrow": ("words", "other-language words for the day after tomorrow"),
        "next_week": ("words", "other-language words for next week"),
        "next_month": ("words", "other-language words for next month"),
    },
    "pages": {
        "board_label": ("words", "other-language words for the Board label of a turn's closing board line"),
        "no_change": ("words", "other-language words for 'no change' in that line"),
    },
    "rebullet": {
        "pronouns": ("words", "other-language pronouns a rewrite must not resolve into a name (matched as whole words)"),
        "negations": ("words", "other-language negation words or endings a rewrite must not lose (matched anywhere in a word)"),
        "negation_words": ("words", "other-language negation words matched only as whole words"),
    },
    "reports": {
        "ask_words": ("words", "other-language words that make a report an ask (needs, please review, decide, approve)"),
    },
    "draft": {
        "stems": ("words", "other-language words that say a step posts, sends or pastes a text (matched anywhere in the step)"),
        "stem_patterns": ("patterns", "regular expressions for such words that need a condition after them (found anywhere in the step)"),
        "standalone_stems": ("words", "such words that count only as a whole word, with at most one particle after them"),
        "particles": ("words", "the particles that may follow a standalone stem"),
        "ignore_phrases": ("words", "phrases that contain a stem but are not about posting a text (a screen share)"),
    },
    "waiting": {
        "park_words": ("words", "other-language words for park, postpone or hold: the owner's answer with one parks the item"),
    },
    "ask_options": {
        "particles": ("words", "the suffixes that may follow the last word of an option's label in a Recommend sentence (a language that glues them on): the label still counts as named"),
        "refusals": ("words", "other-language words or phrases that say 'not this option' right before a label, letter or place (the English ones are not, no, avoid, never, skip, except, don't, instead of, rather than): the option after one is turned away"),
        "refusals_after": ("words", "other-language words that say 'not this option' right after a label (a language that puts the refusing word after it): the option right before one is turned away"),
    },
    "server": {
        "command_cues": ("words", "other-language words that say an item waits on the owner running or pasting a command"),
    },
}


def keywords(feature: str, key: str, cfg: dict[str, Any] | None = None) -> tuple[str, ...]:
    """[keywords.<feature>] <key>: the extra words or patterns of that key, in file order, trimmed, without blanks and repeats. A missing section, a missing key and a value that is not a list of strings
    (a bare string counts as a one-item list) are () : the English behavior. Read where it is used, so a reload is seen at once."""
    v = get("keywords", feature, key, cfg=cfg)
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, (list, tuple)):
        return ()
    out: list[str] = []
    for x in v:
        if isinstance(x, str) and x.strip() and x.strip() not in out:
            out.append(x.strip())
    return tuple(out)


def _kw_one(word: str, kind: str, ws: str) -> str | None:
    if kind == "patterns":
        try:
            re.compile(word)
        except re.error:
            return None
        return "(?:" + word + ")"
    return ws.join(re.escape(p) for p in word.split())


def kw_alt(feature: str, key: str, ws: str = r"\s*") -> str:
    """The configured words of a key as one regex alternation (longest first; a space inside a phrase becomes `ws`), "" when the key is empty. A pattern that does not compile is left out."""
    kind = KEYWORDS.get(feature, {}).get(key, ("words", ""))[0]
    parts = [p for p in (_kw_one(w, kind, ws) for w in sorted(keywords(feature, key), key=len, reverse=True)) if p]
    return "|".join(parts)


def kw_or(feature: str, key: str, ws: str = r"\s*") -> str:
    """`|` + the alternation of a key, or "" when it is empty: appended to an English alternation, so an empty key leaves the pattern as it was."""
    a = kw_alt(feature, key, ws)
    return "|" + a if a else ""


def kw_pipe(alt: str) -> str:
    """`|` + an alternation, or "" when it is empty (a key with no words leaves the pattern it is appended to as it was)."""
    return "|" + alt if alt else ""


_NEVER = r"(?!x)x"      # a pattern nothing matches: a key with no words


_KW_RX: dict[tuple, Any] = {}


def kw_rx(name: str, build, specs: tuple[tuple[str, str], ...], flags: int = 0):
    """re.compile(build(*alts), flags), where alts[i] is kw_alt(*specs[i]) for each (feature, key) of specs; compiled once per set of words (a reload that changes a list builds a new one).
    `name` tells the patterns of different callers apart."""
    alts = tuple(kw_alt(f, k) for f, k in specs)
    key = (name, flags, alts)
    if key not in _KW_RX:
        _KW_RX[key] = re.compile(build(*alts), flags)
    return _KW_RX[key]


def keyword_notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """notes() lines for [keywords]: a section or key this version does not read, a value that is not a list of strings, a pattern that does not compile."""
    kw = get("keywords", cfg=cfg)
    if kw is None:
        return []
    if not isinstance(kw, dict):
        return ["[keywords] is not a table, so no extra words are used: write each list under [keywords.<feature>] (the example config shows them)"]
    out: list[str] = []
    for feat, sec in kw.items():
        known = KEYWORDS.get(feat)
        if known is None:
            out.append(f"[keywords.{feat}] is not read by this version, so its words are unused: the features are {', '.join(sorted(KEYWORDS))}")
            continue
        if not isinstance(sec, dict):
            out.append(f"[keywords.{feat}] is not a table, so its words are unused: write the lists under it")
            continue
        for key, val in sec.items():
            if key not in known:
                out.append(f"[keywords.{feat}] {key} is not read by this version, so it is unused: the keys are {', '.join(sorted(known))}")
                continue
            vals = [val] if isinstance(val, str) else val
            if not isinstance(vals, (list, tuple)) or not all(isinstance(x, str) for x in vals):
                out.append(f"[keywords.{feat}] {key} is not a list of strings, so no extra words are used: write {key} = [\"word\", \"another\"]")
                continue
            if known[key][0] == "patterns":
                for p in vals:
                    try:
                        re.compile(p)
                    except re.error as e:
                        out.append(f"[keywords.{feat}] {key}: the pattern {p!r} does not compile ({e}), so it is left out")
    return out


def recycle_when_idle() -> list[str]:
    """[fleet] recycle_when_idle: the command, as words, that asks the fleet tool for a pane recycle once the box is idle; the
    reason is appended as its last argument. Sessions are told to run it when no item covers a change (the recycle gate and
    recycle-due), and release.sh runs it on a recycle (picked from the PR's files, or --recycle) when no item was flagged. "" (the default) = no such command: nothing
    is run and no session is told to run one."""
    import shlex
    try:
        return shlex.split(str(get("fleet", "recycle_when_idle") or ""))
    except ValueError:
        return []


def notice_cmd() -> list[str]:
    """[fleet] notice_cmd: the command, as words, that tells the running sessions about a change they should know but need not
    reload (a rule, a tool's wording). release.sh runs it after a green deploy whose session pick is a notice, one argument
    appended, "<title> — <summary>" (newlines and tabs as spaces, cut to 400 characters). "" (the default) = no such command: the release logs that none is
    set and goes on."""
    import shlex
    try:
        return shlex.split(str(get("fleet", "notice_cmd") or ""))
    except ValueError:
        return []


_REPO_NAME = re.compile(r"[\w.-]+/[\w.-]+")


def moved_repos() -> dict[str, str]:
    """[github.moved]: the repositories transferred to another owner, old "owner/repo" → new "owner/repo", both lower-cased. Empty (the
    default) = nothing moved. An entry whose key or value is not in owner/repo form, is not text, or maps a name to itself is ignored, and
    so is a table that is not a table, so a malformed table changes nothing. Every entry on a cycle (a → b with b → a, or a longer one) is dropped too: such a pair has no current name. Read at each call (CFG is swapped whole on a reload), so
    adding the entries on the day of a transfer needs a config reload (SIGHUP), not a restart."""
    m = get("github", "moved")
    out: dict[str, str] = {}
    for k, v in (m.items() if isinstance(m, dict) else ()):
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        a, b = k.strip().lower(), v.strip().lower()
        if a != b and _REPO_NAME.fullmatch(a) and _REPO_NAME.fullmatch(b):
            out[a] = b
    loops: set[str] = set()                         # a → b and b → a, or any longer cycle: no repository has "moved" to where it came from, so every entry on one is dropped
    for start in out:
        path, r = [], start
        while r in out and r not in path:
            path.append(r); r = out[r]
        if r in path: loops.update(path[path.index(r):])
    return {k: v for k, v in out.items() if k not in loops}


def canon_repo(name: Any) -> str:
    """A repository name through [github.moved]: "owner/repo" (any case) → its current name, lower-cased; a name not in the table is only
    lower-cased and stripped, and what is not owner/repo is returned that way unchanged. Chains are followed (a → b → c gives c), so an
    old and a new name of one repository compare equal (moved_repos leaves no cycle, the seen set is only a guard). Every comparison of two repository names goes through this on both sides;
    stored names are never rewritten."""
    r = str(name or "").strip().lower()
    moved = moved_repos()
    seen = {r}
    while r in moved and moved[r] not in seen:      # the seen set ends a loop (a → b → a) after one hop
        r = moved[r]
        seen.add(r)
    return r


def released_repos() -> dict[str, Path]:
    """[released.repos]: the other repositories whose pull requests count as released here, "owner/repo" (lower-cased, through [github.moved]) → the local checkout that holds their live copy
    (`"owner/repo" = { checkout = "/abs/path" }`; ~ expanded, absolute). A pull request of such a repository is live when its merge commit is an ancestor of that checkout's HEAD. Absent (no
    defaults are merged) = none: only this repository's pull requests are released. An entry whose key is not owner/repo or whose checkout is not an absolute path is ignored, and so is a table
    that is not a table (released_notes says so). Read at each call: a reload applies it."""
    t = get("released", "repos")
    out: dict[str, Path] = {}
    for k, v in (t.items() if isinstance(t, dict) else ()):
        co = v.get("checkout") if isinstance(v, dict) else None
        a = str(k).strip().lower()
        if isinstance(k, str) and _REPO_NAME.fullmatch(a) and isinstance(co, str) and co.strip() and os.path.isabs(os.path.expanduser(co.strip())):
            out[canon_repo(a)] = Path(os.path.expanduser(co.strip()))
    return out


def released_notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """Lines for the entries of [released.repos] that are ignored (see released_repos): said at the start and on a reload, since an ignored entry leaves its repository refused without a word."""
    t = get("released", "repos", cfg=cfg)
    if t is None:
        return []
    if not isinstance(t, dict):
        return ["[released.repos] is not a table, so no other repository's pull requests are read as released: write each as \"owner/repo\" = { checkout = \"/abs/path\" }"]
    out = []
    for k, v in t.items():
        co = v.get("checkout") if isinstance(v, dict) else None
        if not (_REPO_NAME.fullmatch(str(k).strip().lower()) and isinstance(co, str) and os.path.isabs(os.path.expanduser(co.strip()))):
            out.append(f"[released.repos] {k!r} is ignored: it needs the form \"owner/repo\" = {{ checkout = \"/absolute/path\" }}")
    return out


def canon_name(name: Any) -> str:
    """canon_repo for a name that [github.moved] knows (an old or a current name of a transferred repository), the name exactly as given
    for any other: a stored id keeps its case, and an empty table changes nothing. For code that builds a key from a stored name."""
    r = str(name or "").strip().lower()
    moved = moved_repos()
    return canon_repo(r) if r in moved or r in moved.values() else str(name or "")


def repo_aliases(name: Any) -> set[str]:
    """Every name [github.moved] gives the repository `name` is (it, its current name and each earlier one), lower-cased. For the matching of an
    "owner/*" entry, which has to see the owner a repository used to have."""
    c = canon_repo(name)
    out = {c, str(name or "").strip().lower()}
    out.update(k for k in moved_repos() if canon_repo(k) == c)
    return out


# [units] scope and the four [client] mode keys: one value each is left, the others were
# removed. A file that still carries a key at that value loads as before (the line can go; doctor lists it); any other value
# stops every reader of this module with the line below, never a silent remap: a system-scope instance is never installed
# over with user units, and no box runs a mode the code no longer has. What the removed modes did is described in the last release
# that had them (its stackshot.example.toml, [units] and [client]), which this repository does not keep.
REMOVED = {
    ("units", "scope"): ("user", "the units are user units, systemctl --user; an instance still installed under /etc/systemd/system moves first: "
                                 "https://github.com/howardpark-ai/stackshot/blob/main/INSTALL.md#an-instance-installed-in-the-system-scope"),
    ("client", "reads"): ("api", "a machine that is not the server box reads the page registry and page times through the server's client API"),
    ("client", "sessions"): ("client", "the server learns its sessions and machines from its own clients, the pullers and the hooks"),
    ("client", "delivery"): ("inbox", "a line for a pane on another machine waits in the server's inbox for that machine's puller"),
    ("client", "liveness"): ("puller", "a machine is online while its puller checks in, within online_minutes"),
}


def refused(cfg: dict[str, Any] | None = None) -> list[str]:
    """One line per key of REMOVED whose value in the file (or in `cfg`) is not the one left; [] when the file is fine."""
    out = []
    for (sec, key), (keep, what) in REMOVED.items():
        v = get(sec, key, cfg=cfg)
        if v is None or str(v).strip().lower() == keep:
            continue
        out.append(f'[{sec}] {key} = "{v}" in {PATH}: removed; "{keep}" is the one value left ({what}) '
                   f'— set {key} = "{keep}" or drop the line')
    return out


def obsolete() -> list[str]:
    """The keys of REMOVED still in the file (at their one value, or refused() would have stopped the import): doctor lists them."""
    return [f"[{sec}] {key}" for (sec, key) in REMOVED if get(sec, key) is not None]


def secret_file_mode_problem(path: str) -> str:
    """"" when the file at `path` (a `[[brains]]` secret_file) is not readable by group or others (mode & 0o077 == 0), or does not exist (the
    read says so); else a few words saying it is, with the mode. Never reads the file."""
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return ""
    return f"is readable by group or others (mode {mode & 0o777:04o}), so it is not used: chmod 600 it" if mode & 0o077 else ""


def prefix_folder(prefix: str) -> str:
    """The page folder a [[brains]] prefix points into: everything before its last "/" ("projects/beta-" -> "projects"; "projects/beta/" -> "projects/beta");
    "" when the prefix has no "/" (a page key always starts with a folder, so such a prefix matches no page)."""
    p = str(prefix).strip().lstrip("/")
    return p.rsplit("/", 1)[0] if "/" in p else ""


def _copy_readable(path: str) -> bool:
    """True when a brain's local copy is there to look into: a git copy that holds a page in some page folder. A missing, unmounted or half-cloned
    copy is not judged (the readers already say so). The look costs a few directory reads and no network."""
    root = Path(path)
    if not (root / ".git").exists():
        return False
    for sub in page_dirs():
        try:
            if next((root / sub).rglob("*.md"), None) is not None:
                return True
        except OSError:
            pass
    return False


def _prefix_folder_notes(name: str, b: dict[str, Any], prefixes: Any) -> list[str]:
    """One line for each [[brains]] prefix that names no folder in the brain's local copy: every page under such a prefix reads as missing."""
    path = os.path.expanduser(str(b.get("path") or "").strip())
    if not path or not _copy_readable(path):
        return []
    out: list[str] = []
    for p in [prefixes] if isinstance(prefixes, str) else prefixes:
        if not isinstance(p, str) or not p.strip():
            continue
        folder = prefix_folder(p)
        if folder and (Path(path) / folder).is_dir():
            continue
        what = f"no folder {folder!r} in its local copy {path}" if folder else f"no folder part in it (a page key starts with its folder, as in projects/beta-) to look for in {path}"
        out.append(f"[[brains]] {name} prefix {p.strip()!r} has {what}, so every page under it reads as missing: "
                   f"fix the prefix, or bring the copy up to date if the folder is new there")
    return out


def _strs_ok(v: Any) -> bool:
    """True when a list-of-strings key holds at least one usable (non-empty string) item."""
    return any(isinstance(x, str) and x.strip() for x in ([v] if isinstance(v, str) else v if isinstance(v, (list, tuple)) else []))


def _new_page_notes(name: str, b: dict[str, Any]) -> list[str]:
    """One line for each bad value of a [[brains]] entry's `new_prefixes` or `keep`. A bad value is ignored (brains.extra), never an error:
    a key that is not a string or a list of strings is left out whole, a non-string item or an empty one is skipped, a `new_prefixes` entry
    without a "/" after its folder part matches no page key, one that does not end in "-" or "/" also catches longer names, and a `keep`
    with no `new_prefixes` changes nothing."""
    out: list[str] = []
    for key in ("new_prefixes", "keep"):
        v = b.get(key)
        if v is None:
            continue
        if not isinstance(v, (str, list, tuple)):
            out.append(f"[[brains]] {name} {key} is not a list of strings, so it is ignored: write {key} = [\"projects/beta-\"]" if key == "new_prefixes"
                       else f"[[brains]] {name} {key} is not a list of strings, so it is ignored: write {key} = [\"beta-old\"]")
            continue
        for x in [v] if isinstance(v, str) else v:
            if not isinstance(x, str) or not x.strip():
                out.append(f"[[brains]] {name} {key} holds {x!r}, which is not a non-empty string, so it is skipped")
            elif key == "new_prefixes" and "/" not in x.strip().lstrip("/"):
                out.append(f"[[brains]] {name} new_prefixes {x.strip()!r} has no \"/\" (a page key starts with its folder, as in projects/beta-), so it matches no page")
            elif key == "new_prefixes" and not x.strip().endswith(("-", "/")):
                out.append(f"[[brains]] {name} new_prefixes {x.strip()!r} does not end in \"-\" or \"/\", so it also catches longer names: end it with the separator, for example {x.strip() + '-'!r}")
    if b.get("keep") and not _strs_ok(b.get("new_prefixes")):
        out.append(f"[[brains]] {name} has keep but no new_prefixes, so keep changes nothing: add new_prefixes or remove keep")
    return out


def notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """Settings problems that do not stop the start but change behaviour silently: one line each, [] when the file is fine. The config
    is exactly one file with no defaults merged in (see the head), so a [page_gate] without keeper_currency means the page rules
    are off. the old key steward_currency is no longer read, so a file holding only that one lands here too. a file that still carries the retired [runner] enabled or [router] page_debt_hour is told it can go; the key changes nothing. a [presence] minutes that is
    not a number above 0 is read as 30 (the default), so it is said here, at the start and on a reload, instead of changing silently. a paused stall pass is named first."""
    out: list[str] = stall_notes(cfg)
    out += keyword_notes(cfg)
    if not str(get("instance", "owner", cfg=cfg) or "").strip():
        out.append('[instance] has no owner, so the board names its person by a placeholder: set owner = "<first name>" (the example config has it)')
    pg = get("page_gate", cfg=cfg)
    pg = pg if isinstance(pg, dict) else {}
    if "keeper_currency" in pg:
        pass
    elif "steward_currency" in pg:
        out.append('[page_gate] steward_currency is no longer read, so the page rules are off: rename it to keeper_currency = "keepers"')
    else:
        out.append('[page_gate] has no keeper_currency, so the page rules are off: set keeper_currency = "keepers" (the example config has it)')
    rn = get("runner", cfg=cfg)
    if isinstance(rn, dict) and "enabled" in rn:
        out.append("[runner] enabled is retired and read by nothing: the minute set's runner is the only path and always starts; drop the line")
    ro = get("router", cfg=cfg)
    if isinstance(ro, dict) and "page_debt_hour" in ro:
        out.append("[router] page_debt_hour is retired and read by nothing: the page-debt call runs with each audit run ([audit] at), no longer from an hour of its own; drop the line")
    if isinstance(ro, dict) and (ro.get("page_debt") is True or str(ro.get("page_debt")).strip().lower() in ("true", "1", "yes", "on")):
        au = get("audit", cfg=cfg)
        au = au if isinstance(au, dict) else {}
        if not (au.get("enabled") is True or str(au.get("enabled")).strip().lower() in ("true", "1", "yes")) or str(au.get("mode") or "").strip().lower() == "agent":
            out.append('[router] page_debt is on, but the page-debt call is made by the audit run\'s pages stage: with [audit] enabled off or mode = "agent" no pass runs and the page debts wait; turn the audit on in script mode')
    br = get("brains", cfg=cfg)
    if br is not None and not isinstance(br, list):
        out.append("brains is not a list of [[brains]] tables, so no second brain is used: write each one as a [[brains]] table (the example config has one)")
    seen: set[str] = set()
    for i, b in enumerate(br if isinstance(br, list) else [], 1):
        if not isinstance(b, dict) or not str(b.get("name") or "").strip() or not str(b.get("path") or "").strip() or str(b.get("name")).strip() == "default":
            out.append(f"[[brains]] entry {i} has no name or path (or is named \"default\"), so it is skipped and its pages are read from the default brain: give it a name and its local copy's path")
            continue
        name = str(b.get("name")).strip()
        if name in seen:
            out.append(f"[[brains]] entry {i} repeats the name {name!r}: a warning and a lookup by that name reach the first entry only; give each brain its own name")
        seen.add(name)
        if not (b.get("slugs") or b.get("prefixes") or b.get("new_prefixes")):
            out.append(f"[[brains]] {name} names no slugs and no prefixes, so no page is read from it: list the page keys it holds")
        pf = b.get("prefixes") or []
        for p in [pf] if isinstance(pf, str) else pf:
            if isinstance(p, str) and p.strip() and not p.strip().endswith(("-", "/")):
                out.append(f"[[brains]] {name} prefix {p.strip()!r} does not end in \"-\" or \"/\", so it also catches longer names (projects/beta also takes projects/betamax): end it with the separator, for example {p.strip() + '-'!r}")
        out.extend(_prefix_folder_notes(name, b, pf))
        out.extend(_new_page_notes(name, b))
        sf = b.get("secret_file")
        if sf is not None and not isinstance(sf, str):
            out.append(f"[[brains]] {name} secret_file is not a path, so no client secret is passed to its gbrain CLI: set secret_file = \"<path of the file holding the client_secret>\" or remove the key")
        elif isinstance(sf, str) and sf.strip():
            full = os.path.expanduser(sf.strip())
            bad = secret_file_mode_problem(full)
            if bad:
                out.append(f"[[brains]] {name} secret_file {full} {bad}")
        if not str(b.get("home") or "").strip() and not b.get("remote"):
            out.append(f"[[brains]] {name} has no home, so its pages are neither read nor written through the gbrain CLI (the CLI would run on the default brain): set home = \"<its GBRAIN_HOME folder>\" on that entry")
    out.extend(released_notes(cfg))
    out.extend(report_notes(cfg))
    pm = get("presence", "minutes", cfg=cfg)
    if pm is not None:
        try:
            ok = not isinstance(pm, bool) and float(pm) > 0
        except (TypeError, ValueError):
            ok = False
        if not ok:
            out.append(f"[presence] minutes = {pm!r} is not a number above 0, so 30 minutes is used: set a number of minutes above 0")
    return out


def stall_item_answers(item: str) -> list[dict[str, Any]] | None:
    """The owner's answers (metadata.answers) on the board item `item` names (board#N, #N, a stored id such as g7, an old id), read from the store; None when `item` is no item the store holds.
    Lazy import: ghsync imports this module."""
    import json
    import re
    from stackshot.github import ghsync as _gh
    t = str(item or "").strip().lower()
    g = _gh.norm(t) or (t if re.fullmatch(r"[a-z][1-9]\d*", t) else "")
    if not g:
        return None
    g = _gh.resolve(g)
    try:
        it = json.loads(path("paths", "store").joinpath(g[0], f"{g[1:]}.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    v = (it.get("metadata") or {}).get("answers") if isinstance(it, dict) else None
    return [a for a in v if isinstance(a, dict)] if isinstance(v, list) else []


def stall_auth(st: dict[str, Any] | None):
    """the rule for a pause of the stall pass, as `stall.pause` takes it: `auth(since)` → "" when [stall] pause_item names a board item that carries the owner's own answer approving a pause (stall.authorize) dated within
    stall.ANSWER_HOURS of `since` (when the server first saw the pause), else why not. Never raises: a failure reads as no answer, so the pause is refused and the pass runs."""
    from stackshot.waits import stall as _stall
    item = str((st or {}).get("pause_item") or "").strip()

    def auth(since: float) -> str:
        try:
            return _stall.authorize(item, stall_item_answers(item) if item else None, since)
        except Exception as e:
            return f"[stall] pause_item {item or '(none)'} could not be read ({e.__class__.__name__}): the pause is not honored"
    return auth


def stall_notes(cfg: dict[str, Any] | None = None) -> list[str]:
    """a pause of the stall pass ([stall] enabled = false, or a paused_until still ahead) is a setting that changes behaviour, so doctor, the server's start and a reload name it with its end time.
    The end is the one the server keeps (<state>/stall_pause.json, from when it first saw the pause); a pause it has not read yet counts from now. A paused_until that is not a time is named and ignored.
    a pause the owner has not answered for (`stall_auth`) is named as refused, with the reason: the pass keeps running.
    [] when nothing is paused or the end cannot be told."""
    try:
        st = get("stall", cfg=cfg)
        if not isinstance(st, dict) or (st.get("enabled", True) and st.get("paused_until") in (None, "")):
            return []
        import datetime
        import json
        import time
        from stackshot.waits import stall as _stall
        now = time.time()
        bad = []
        if st.get("paused_until") not in (None, "") and _stall.parse_until(st.get("paused_until"), tz()) is None:
            bad = [f'[stall] paused_until = {str(st.get("paused_until"))!r} is not an ISO-8601 time (like "2099-03-14T21:00+00:00"): ignored']
        rec = None
        if cfg is None or cfg is CFG:                    # the running config (a reload's notes(new) is called with it, after CFG is swapped): the server's record of the pause is the truth; any other dict is a what-if
            try:
                d = json.loads(state("stall_pause.json").read_text(encoding="utf-8"))
                rec = d if isinstance(d, dict) else None
            except Exception:
                rec = None
        hours = _stall.pause_hours(st.get("max_pause_hours", _stall.PAUSE_HOURS))
        new, end, why, _ev = _stall.pause(st.get("enabled", True), st.get("paused_until", ""), tz(), hours, rec, now, stall_auth(st))
        if "refuse" in _ev:
            return bad + [f"{why}; the pause setting is refused and the stall pass keeps running"]
        if end is None:
            return bad
        t = datetime.datetime.fromtimestamp(end, tz())
        d = t.day
        shown = f"{t:%a %b} {d}{'th' if 11 <= d % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(d % 10, 'th')} {t:%H:%M} {t:%Z}"
        seen = bool(rec) and rec.get("sig") == new.get("sig") if new else False
        return bad + [f"[stall] the stall pass is paused ({why}) and takes no step until {shown}"
                      + ("" if seen else " (counted from now: the server has not read this pause yet)") + "; it runs again on its own then, with no edit"]
    except Exception:
        return []


_bad = refused()
if _bad:
    raise SystemExit("\n".join(_bad))


# Settings a reload does not apply: what the running process wired in at its start. A reload that changes one logs
# "<key> changed: takes effect at the next restart" and keeps the running value in CFG, so every reader still agrees with
# what is wired. A section name covers all its keys. The note says what else the change needs.
RESTART_ONLY: dict[str, str] = {
    "server": "",                                 # host, port, path: uvicorn binds and mounts them at start
    "server.port": "after ./install.sh units",    #   (anchor-hub's unit waits for the server on its port)
    "auth.mode": "",                              # the OAuth provider is built at import (_auth): Google client, base URL,
    "auth.base_url": "",                          #   redirect URIs, the portal token's identity
    "auth.allowed_client_redirect_uris": "",
    "auth.portal_identity": "",
    "paths": "",                                  # the store, state and secrets dirs hold the running process's files, ids and locks,
                                                  #   and anchor-hub watches them; the others are tied to them (a path move is a restart)
    "ids.letter": "",                             # its store dir is made at import; named in the connector's instructions
    "github.issues_letter": "",                   # the store letter of issue-numbered items: the files already written under it stay
    "github.local_letter": "",                    # the same for the items created while GitHub was down
    "instance.name": "",                          # these are written into the MCP tool descriptions and the connector's
    "instance.owner": "",                         #   instructions when the tools are registered at start
    "instance.owner_aliases": "",
    "steps": "",                                  # the shell rule is written into the create and update descriptions at start
    "instance.board_url": "",
    "instance.machine": "",                       # written into a temporary id (board-tmp-<machine>#<n>) and its page address
    "instance.timezone": "after ./install.sh units",   # (and anchor-hub's unit TZ)
    "subject.prefixes": "",
    "fleet.operator_label": "",
    "fleet.tool_name": "",                        # these two are written into the update tool's description at start
    "fleet.recycle_when_idle": "",
    "freshness": "",
    "anchor_hub.hook_url": "",                    # anchor-hub's webhook receiver is bound at start and the Drive/Gmail watch
    "anchor_hub.hook_port": "",                   #   channels are registered with Google at that address
    "anchor_hub.slack_team": "",                  # read when the receivers start (Slack's permalink host, the owner's Notion ids)
    "anchor_hub.self_emails": "",
    "anchor_hub.gmail_topics": "",                # a Gmail watch keeps the topic it was registered with; a restart re-registers it
    "anchor_hub.enabled": "after ./install.sh units",   # these four decide which units install.sh installs, and when
    "audit.enabled": "after ./install.sh units",
    "audit.at": "after ./install.sh units",
    "portal": "after ./install.sh units",
}


def _restart_only(key: str) -> str | None:
    """The RESTART_ONLY entry covering a dotted key (its note), or None when the key is live."""
    sec = key.split(".", 1)[0]
    return RESTART_ONLY.get(key, RESTART_ONLY.get(sec))


def _flat(cfg: dict[str, Any]) -> dict[str, Any]:
    """{"section.key": value} for every key of every section (a top-level value that is not a section: "key")."""
    out: dict[str, Any] = {}
    for s, v in cfg.items():
        if isinstance(v, dict):
            out.update({f"{s}.{k}": x for k, x in v.items()} or {s: {}})
        else:
            out[s] = v
    return out


def _say(line: str) -> None:
    print(f"config reload: {line}", file=sys.stderr, flush=True)


_MISSING = object()
PENDING: list[str] = []      # the RESTART_ONLY keys whose value in the file differs from the running one, after the last reload


def reload() -> list[str] | None:
    """Re-read the file (PATH) and check it as `config.py check` does. Valid: swap CFG at once and → the live keys that changed
    ([] for none); a changed RESTART_ONLY key keeps its running value and is logged, never applied. Invalid (a TOML syntax
    error, a missing file, a refused key): log why, keep CFG as it is and → None. Never raises."""
    global CFG, PENDING
    try:
        new = load(PATH)
        bad = refused(new)
        if bad:
            _say("refused, the running config is kept:\n" + "\n".join(bad)); return None
        old = CFG
        fo, fn = _flat(old), _flat(new)
        changed = sorted(k for k in fo.keys() | fn.keys() if fo.get(k, _MISSING) != fn.get(k, _MISSING))
        held = [k for k in changed if _restart_only(k) is not None]
        for k in held:                                  # keep what is wired: the running value (or its absence) stays in CFG
            sec, _, key = k.partition(".")
            if not key:
                if k in fo: new[sec] = fo[k]
                else: new.pop(sec, None)
                continue
            if not isinstance(new.get(sec), dict):
                new[sec] = {}
            if k in fo: new[sec][key] = fo[k]
            else: new[sec].pop(key, None)
        CFG = new
        PENDING = held
        for n in notes(new):
            _say(n)
        for k in held:
            note = _restart_only(k)
            _say(f"{k} changed: takes effect at the next restart" + (f" ({note})" if note else ""))
        return [k for k in changed if k not in held]
    except Exception as e:                              # tomllib.TOMLDecodeError, OSError, anything else: the old config stays
        _say(f"{PATH} not loaded, the running config is kept: {type(e).__name__}: {e}")
        return None


if __name__ == "__main__":
    a = sys.argv[1:]
    if a == ["file"]:
        print(PATH); sys.exit(0)
    if a == ["check"]:                # a removed mode in the file already stopped the import above with its line; here: nothing to say
        sys.exit(0)
    if len(a) < 2 or a[0] not in ("get", "path", "state", "secrets"):
        sys.exit("usage: config.py get a.b.c | path a.b | state <parts…> | secrets <parts…> | file | check")
    if a[0] == "get":
        v = get(*a[1].split("."))
        print("" if v is None else v if isinstance(v, str) else __import__("json").dumps(v))
    elif a[0] == "path":
        print(path(*a[1].split(".")))
    elif a[0] == "state":
        print(state(*a[1:]))
    else:
        print(secrets(*a[1:]))
