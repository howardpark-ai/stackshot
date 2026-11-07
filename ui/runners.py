"""ui/runners.py — the page half of runners.py: the count cards, the machines' table, the Disable / Enable forms and the refresh script, with every
address written through under() (the root).

The snapshot, the switch and the settings (snapshot, peek, switch_box, switch_boxes, switch_enabled, conf, ORG_MARK, SWITCH_ACTIONS) are runners.py's. Only the
markup, the style and the script are here."""
from __future__ import annotations

import html as _html
import json
import re
import urllib.parse
from typing import Any

import config as _cfg
from runners import ORG_MARK, SWITCH_ACTIONS, _columns, _machines, _now, asof_html, conf, pending_html, switch_boxes, switch_enabled
from ui import under

# ----------------------------------------------------------------------------- the page
def _e(s: Any) -> str:
    return _html.escape(str(s), quote=True)


def _natural(name: str) -> list[Any]:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", name)]


def _dur(s: float) -> str:
    s = max(0, int(s))
    if s < 60:
        return f"{s}s"
    m = s // 60
    return f"{m}m" if m < 60 else f"{m // 60}h {m % 60:02d}m"


def _running(x: dict[str, Any], now: float) -> str:
    j = x["job"] or {}
    ph = j.get("phase") if j.get("phase") in ("starting", "finishing") else ""
    repo = j.get("repo") or ("" if x["repo"].endswith(ORG_MARK) else x["repo"])      # an org runner whose job was not found has no repo to name
    full = j.get("full") or (f"{conf('owner')}/{repo}" if conf("owner") else repo)      # owner/name for github.com: the run's own full_name (it follows a transfer), else [runners] owner
    if j.get("pr"):
        what = f'<a href="https://github.com/{_e(full)}/pull/{int(j["pr"])}" target="_blank" rel="noopener">{_e(repo)} #{int(j["pr"])}</a>'
    elif j.get("branch"):
        href = j.get("url") or f"https://github.com/{full}/tree/{urllib.parse.quote(j['branch'], safe='/')}"
        what = f'<a href="{_e(href)}" target="_blank" rel="noopener">{_e(repo)} {_e(j["branch"])}</a>'
    elif ph:                                                  # no PR or branch to link: the repo and the run's name
        what = " · ".join(p for p in (_e(repo), _e(j.get("run") or "")) if p)
    else:
        what = f"{_e(repo)}, job not found" if repo else "job not found"
    if ph:                                                    # the job's start or end gap, told as such: GitHub's lists are seconds behind the runner
        what = f"{what} · {ph} job…" if what else f"{ph} job…"
    since = f" · {_dur(now - j['started'])}" if j.get("started") else ""
    return f'<span class="rjob">{what}{since}</span>'


def _tag(col: str) -> str:
    return col[:-len(ORG_MARK)] + " (shared)" if col.endswith(ORG_MARK) else col


def _li(x: dict[str, Any], now: float, tag: str = "") -> str:
    """One runner: a dot, its name, its state word and what goes with it (the job it is on; why it is offline or disabled). `tag` is the repo list it came from, when the page has more than one."""
    st = x["state"]
    if st == "running":
        cls, word = "running", "running"
        tail = _running(x, now) + (' <span class="rwhy">· finishes, then stops</span>' if x.get("stopping") else "")
    elif x.get("disabled"):
        cls, word = "off", "disabled"
        tail = "" if x["reason"].startswith("disabled on ") or not x["reason"] else f'<span class="rwhy switch">{_e(x["reason"])}</span>'      # "disabled on <box>" says what the machine's row says already
    elif st == "offline":
        cls, word = ("fault", "offline") if x["kind"] == "fault" else ("idle", "restarting") if x["kind"] == "restarting" else ("offline", "offline")      # restarting: the idle dot and style, no red
        tail = f'<span class="rwhy {_e(x["kind"])}">{"⚠ " if x["kind"] == "fault" else ""}{_e(x["reason"])}</span>'
    else:
        cls, word, tail = "idle", "idle", ""
    tg = f' <span class="rtag">{_e(tag)}</span>' if tag else ""
    return (f'<li class="rn {cls}"><span class="rdot" aria-hidden="true"></span><b class="rname">{_e(x["name"])}</b> '
            f'<span class="rst">{word}</span>{tg}{" " + tail if tail else ""}</li>')


def tally(snap: dict[str, Any]) -> dict[str, int]:
    """The count cards: runners (all), running (a job on it), idle (online, free, not disabled), disabled (stopped taking jobs on purpose, by the machine's switch or a hold; not one still on a job) and
    offline (GitHub lists it offline although nothing disabled it, and for OFFLINE_GRACE_S (5 minutes) or more: a fault, or a machine that cannot be reached; a shorter gap is a runner restarting between jobs and counts as idle). The four add up to `runners`."""
    rs = snap.get("runners") or []
    running = sum(1 for x in rs if x["state"] == "running")
    disabled = sum(1 for x in rs if x["state"] != "running" and x.get("disabled"))
    idle = sum(1 for x in rs if (x["state"] == "idle" or x.get("kind") == "restarting") and not x.get("disabled"))      # a runner offline for less than OFFLINE_GRACE_S is between two jobs: idle, not a fault
    offline = sum(1 for x in rs if x["state"] == "offline" and x.get("kind") != "restarting" and not x.get("disabled"))
    return {"runners": len(rs), "running": running, "idle": idle, "disabled": disabled, "offline": offline}


def _cards(t: dict[str, int]) -> str:
    def card(cls: str, n: int, label: str) -> str:
        z = "" if n else " zero"
        return f'<div class="rcard {cls}{z}"><b>{n}</b><span>{label}</span></div>'
    return ('<div class="rcards">' + card("", t["runners"], "Runners") + card("run", t["running"], "Running") + card("idle", t["idle"], "Idle")
            + card("off", t["disabled"], "Disabled") + card("bad" if t["offline"] else "", t["offline"], "Offline") + "</div>")


def _machine_state(mine: list[dict[str, Any]], sw: dict[str, Any]) -> tuple[str, str, bool]:
    """(html of the machine's state line, class, dimmed) from its runners and its switch."""
    online = [x for x in mine if x["state"] != "offline" or x.get("kind") == "restarting"]      # a runner restarting between jobs counts as online, as on the cards
    busy = sum(1 for x in online if x["state"] == "running")
    if not sw.get("ok"):
        if sw.get("why") == "unreachable":
            return '<span class="offw">not reachable</span>', "unreachable", False
        return "switch not read", "unread", False
    if sw["mode"] == "off":
        if busy:
            return f'<span class="offw">disabling</span> · {busy} job{"s" if busy != 1 else ""} finishing', "disabling", False
        import datetime as dt
        since = f" since {dt.datetime.fromtimestamp(sw['since'], _cfg.tz()).strftime('%H:%M')}" if sw.get("since") else ""
        return f'<span class="offw">disabled</span>{since}', "disabled", True
    return (f'<span class="on">on</span> · {busy} of {len(online)} busy' if online else '<span class="on">on</span> · no runner online'), "on", False


def _buttons(b: str, sw: dict[str, Any], token: Any) -> str:
    """The machine's Disable / Enable form(s): Disable when its switch is on, Enable when it is off, both when the switch could not be read. Only when the server gave a token maker, a pool-mode.sh
    is configured and the machine is one the button acts on (switch_boxes: a fleet machine, or a [runners] boxes entry named in [runners.ssh_hosts])."""
    if token is None or not switch_enabled() or b not in switch_boxes():
        return ""
    if sw.get("ok"):
        acts = ["on"] if sw["mode"] == "off" else ["off"]
    else:
        acts = ["off", "on"]
    tk = _e(token(b))
    return "".join(f'<form class="mact" method="post" action="{under("/runners/switch")}"><input type="hidden" name="box" value="{_e(b)}"><input type="hidden" name="act" value="{a}">'
                   f'<input type="hidden" name="token" value="{tk}"><button type="submit" class="b">{SWITCH_ACTIONS[a]}</button></form>' for a in acts)


def table_html(snap: dict[str, Any], now: float | None = None, token: Any = None) -> str:
    """Everything the page swaps every 30 s: the as-of line, the errors, the count cards, the machines' table. `token` (server.py) makes a box's form token; None draws no button.
    Escapes everything it draws."""
    now = _now() if now is None else now
    if snap.get("pending"):
        return pending_html()
    cols = _columns(snap)
    boxes = _machines(snap["runners"])
    swm = snap.get("switch") or {}
    out = [asof_html(snap, now)]
    for key, msg in snap["errors"].items():
        out.append(f'<p class="rerr" role="alert">{"" if key.startswith("org:") else "GitHub error: "}{_e(msg)}</p>')
    out.append(_cards(tally(snap)))
    failed = snap.get("failed") or []
    body = []
    for b in boxes:
        mine = sorted((x for x in snap["runners"] if x["box"] == b), key=lambda x: (cols.index(x["repo"]) if x["repo"] in cols else len(cols), _natural(x["name"])))
        sw = swm.get(b) or {"ok": False, "why": "unread"}
        state, scls, dim = _machine_state(mine, sw)
        lis = [_li(x, now, _tag(x["repo"]) if len(cols) > 1 else "") for x in mine]
        for r in cols:                                   # a list GitHub could not give: its runners on this machine are unknown, said once on the row
            if (r in failed or (r.endswith(ORG_MARK) and "org:" + r[:-len(ORG_MARK)] in failed)) and not any(x["repo"] == r for x in mine):
                lis.append(f'<li class="rnone">{_e(_tag(r))}: unknown (GitHub error)</li>')
        cell = '<ul class="rl">' + "".join(lis) + "</ul>" if lis else '<span class="rnone">no runners</span>'
        body.append(f'<tr class="{"isoff" if dim else ""}"><th scope="row"><div class="mname">{_e(b)}</div><div class="mstate {scls}">{state}</div>{_buttons(b, sw, token)}</th><td>{cell}</td></tr>')
    out.append(f'<table class="rtab"><colgroup><col class="m"><col></colgroup><thead><tr><th scope="col">Machine</th><th scope="col">Runners</th></tr></thead><tbody>{"".join(body)}</tbody></table>')
    return "".join(out)


def data(snap: dict[str, Any], now: float | None = None, token: Any = None) -> dict[str, Any]:
    now = _now() if now is None else now
    rs = [{"name": x["name"], "repo": x["repo"], "box": x["box"], "state": x["state"], "reason": x["reason"], "kind": x["kind"], "disabled": bool(x.get("disabled")),
           "job": None if not x["job"] else {**x["job"], "elapsed_s": int(now - x["job"]["started"]) if x["job"]["started"] else None}} for x in snap["runners"]]
    sw = {b: ({"mode": s["mode"]} if s.get("ok") else {"mode": ""}) for b, s in (snap.get("switch") or {}).items()}
    return {"ts": int(snap["ts"]), "stale": bool(snap.get("stale")), "refreshing": bool(snap.get("refreshing")), "pending": bool(snap.get("pending")), "errors": snap["errors"], "counts": tally(snap), "switch": sw, "runners": rs, "html": table_html(snap, now, token)}


_CSS = """
.rcards{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:8px;margin:12px 0 16px}
.rcard{display:flex;flex-direction:column;min-width:0;padding:8px 12px;border:1px solid var(--line);border-radius:10px;background:var(--card)}
.rcard b{font-size:24px;line-height:1.1;font-variant-numeric:tabular-nums}.rcard span{font-size:12px;color:var(--mut);margin-top:2px}
.rcard.zero b{color:var(--mut)}.rcard.run b{color:var(--run)}.rcard.idle b{color:var(--ok)}.rcard.off b{color:var(--warn)}.rcard.bad{border-color:var(--p1)}.rcard.bad b,.rcard.bad span{color:var(--p1)}
.rtab{width:100%;border-collapse:collapse;margin:0 0 12px;font-size:14px}.rtab th,.rtab td{border:1px solid var(--line);padding:10px 12px;text-align:left;vertical-align:top}
.rtab thead th{background:var(--card);font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--mut);font-weight:600}.rtab col.m{width:168px}
.rtab tbody th{background:var(--card);font-weight:400}.mname{font-weight:700;font-size:15px;overflow-wrap:anywhere}
.mstate{font-size:12.5px;color:var(--mut);margin:2px 0 8px}.mstate .on{color:var(--ok);font-weight:600}.mstate .offw{color:var(--warn);font-weight:600}
.mstate.unreachable .offw{color:var(--p1)}form.mact{display:inline-block;margin:0 6px 0 0}form.mact .b{min-width:88px}
.rl{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:minmax(0,1fr);gap:2px 0}
.rl li{padding:3px 0;line-height:1.4;min-width:0;overflow-wrap:anywhere}.rname{font-weight:600}
.rdot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;background:var(--mut);vertical-align:1px}
.rn.idle .rdot{background:var(--ok)}.rn.running .rdot{background:var(--run)}.rn.off .rdot,.rn.offline .rdot{background:transparent;border:2px solid var(--mut);box-sizing:border-box}
.rn.fault .rdot{background:var(--p1)}.rn.fault{color:var(--p1)}.rn.fault .rst,.rn.fault .rwhy{font-weight:700}
.rst{color:var(--mut)}.rn.running .rst{color:var(--run)}.rn.idle .rst{color:var(--ok)}.rn.fault .rst{color:var(--p1)}
.rtag{color:var(--mut);font-size:12px;border:1px solid var(--line);border-radius:4px;padding:0 4px}
tr.isoff td{opacity:.6}[data-stale]{opacity:.55}.rstale,.rstale-js{color:var(--warn);font-weight:600;margin:6px 0}.rstale-js{display:none}.rstale-js.on{display:block}
.rwhy,.rjob,.rnone{color:var(--mut)}.rjob a{color:var(--acc)}.rnone{font-style:italic}.rerr{color:var(--p1);font-weight:600}.rasof{margin:2px 0 0}
#rn-result{margin:8px 0 0;white-space:pre-line;min-height:0}#rn-result.ok{color:var(--ok);font-weight:600}#rn-result.err{color:var(--p1);font-weight:600}
@media(max-width:600px){.rcards{grid-template-columns:repeat(3,minmax(0,1fr))}.rtab,.rtab thead,.rtab tbody,.rtab tr,.rtab th,.rtab td{display:block}.rtab thead,.rtab colgroup{display:none}
.rtab tbody th{border-bottom:0;display:flex;flex-wrap:wrap;align-items:center;gap:4px 12px}.mstate{margin:0}.rtab tbody th form.mact{margin:0 0 0 auto}}
"""
_JS = """<script>(function(){var box=document.getElementById('rn-body'),note=document.getElementById('rn-note'),res=document.getElementById('rn-result'),TZ=%s,last=+box.getAttribute('data-ts')||0,busy=false,quick=0;
function hm(t){try{return new Intl.DateTimeFormat('en-GB',{hour:'2-digit',minute:'2-digit',timeZone:TZ}).format(new Date(t*1000))}catch(e){return new Date(t*1000).toTimeString().slice(0,5)}}
function bad(why){box.setAttribute('data-stale','1');note.textContent=why==='login'?'Not refreshed: sign in again.':'Not refreshed since '+hm(last)+' '+%s+'.';note.className='rstale-js on'}
function load(){if(busy)return;busy=true;var ac=window.AbortController?new AbortController():null,tm=setTimeout(function(){if(ac)ac.abort();busy=false},15000);
fetch('@RUNNERS_JSON@',{cache:'no-store',credentials:'same-origin',headers:{'Accept':'application/json'},signal:ac?ac.signal:undefined})
.then(function(r){if(!r.ok)throw 'http';if((r.headers.get('content-type')||'').indexOf('json')<0)throw 'login';return r.json()})
.then(function(d){box.innerHTML=d.html;last=d.ts;box.setAttribute('data-ts',d.ts);if(d.stale)box.setAttribute('data-stale','1');else box.removeAttribute('data-stale');note.className='rstale-js';if(d.refreshing||d.pending){if(quick++<10)setTimeout(load,3000)}else quick=0})
.catch(function(e){bad(e==='login'?'login':'net')}).then(function(){clearTimeout(tm);busy=false})}
function show(t,ok){res.textContent=t;res.className=t?(ok?'ok':'err'):''}
document.addEventListener('submit',function(e){var f=e.target;if(!f.classList||!f.classList.contains('mact'))return;e.preventDefault();
var b=f.querySelector('button'),was=b.textContent,off=f.elements['act'].value==='off',ac=window.AbortController?new AbortController():null,tm=setTimeout(function(){if(ac)ac.abort()},150000);
b.disabled=true;b.textContent=off?'Disabling\\u2026':'Enabling\\u2026';show('',true);
fetch(f.getAttribute('action'),{method:'POST',credentials:'same-origin',headers:{'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(new FormData(f)).toString(),signal:ac?ac.signal:undefined})
.then(function(r){return r.text().then(function(t){var d=null;try{d=JSON.parse(t)}catch(x){}return {ok:!!(r.ok&&d&&d.ok),text:d&&d.text?d.text:(t||'It did not work ('+r.status+').')}})})
.catch(function(){return {ok:false,text:'No answer from the board. Check the table and try again.'}})
.then(function(o){clearTimeout(tm);show(o.text,o.ok);b.disabled=false;b.textContent=was;busy=false;load();setTimeout(load,10000)})});
if(box.hasAttribute('data-refreshing'))setTimeout(load,2000);
setInterval(function(){if(!document.hidden)load()},30000);document.addEventListener('visibilitychange',function(){if(!document.hidden)load()})})();</script>""".replace("@RUNNERS_JSON@", under("/runners.json"))


def page_html(board: Any, snap: dict[str, Any], token: Any = None) -> str:
    """The CI runners page in the board's chrome (as the search page draws it): the home title bar and side panel, the count cards and table, the refresh script."""
    from ui import render as R
    font_css = str(_cfg.get("instance", "font_css") or "")
    title = f"CI runners · {board.title}"
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f'<meta name="color-scheme" content="light dark"><meta name="robots" content="noindex,nofollow"><title>{_e(title)}</title>'
            f'<link rel="icon" href="{R.icon_href("favicon.svg")}" type="image/svg+xml">' + (f'<link rel="stylesheet" href="{_e(font_css)}">' if font_css else "")
            + R._THEME_HEAD + R._APP_HEAD + f'<style>{board._css()}{_CSS}</style></head>{R._PANEL_BODY}<div id="layout"><main id="top">{board.page_header()}'
            f'<h1>CI runners</h1><p class="sub">GitHub Actions runners on each machine. They belong to the {_e(_org_phrase(snap))} and take jobs from every repo.</p>'
            f'<p id="rn-note" class="rstale-js" role="status"></p><p id="rn-result" role="status" aria-live="polite"></p>'
            f'<div id="rn-body" data-ts="{int(snap["ts"])}"{" data-stale=\"1\"" if snap.get("stale") else ""}{" data-refreshing=\"1\"" if snap.get("refreshing") or snap.get("pending") else ""}>{table_html(snap, token=token)}</div></main>' + board.panel_tail()
            + _JS % (json.dumps(str(_cfg.get("instance", "timezone") or "UTC")), json.dumps(_cfg.tz_abbr())) + R._FAB_PAIR + R._THEME_JS + R._RELOAD_JS + R._TOTOP_JS + R._BFCACHE_JS + '</body></html>')


def _org_phrase(snap: dict[str, Any]) -> str:
    """"<login> org" when the runners are an organization's shared ones, else "repos' own list": the subtitle names whose runners these are."""
    orgs = sorted({x["repo"][:-len(ORG_MARK)] for x in snap.get("runners") or [] if x["repo"].endswith(ORG_MARK)})
    return f"{orgs[0]} org" if len(orgs) == 1 else "repos you list"
