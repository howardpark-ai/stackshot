"""answer_frame.py: the page of GET /items/<key>/answer-frame (docs/answer-frame.md is the contract): one item's answer block as the home page's Your move draws it (the question, the option cards,
the note box, Send), for another site of the instance to show in a frame, and the script that tells that parent page the frame's height and state. The question, the form, the cards, the notices and
the stylesheet are the board's own (ui/render.py); this module adds the page around them and the states a framed block goes through:

    open         he can answer (also after a send that failed, which the frame says in words)
    sending      (the script's own, never drawn by the server) a send is under way
    answered     the recorded answer, nothing to press
    changed      the question is no longer the one this frame drew: a board link
    closed       not on his move, or nothing to pick: a line and a board link
    signed_out   no board session: a board link and no text of the item

The route (web/routes/answer_frame.py) decides who is asking and sends the headers; nothing here writes."""
from __future__ import annotations

import json
from typing import Any

from stackshot.core import config as _cfg, members as _members
from stackshot.model import ask_leaves as _askl, option_labels as _ol
from stackshot.web import home as _home
from stackshot.web.i18n import t as _t
from stackshot.web.ui import render as _r

esc = _r.esc
_QUIET = ("empty", "emptynote", "toolong", "nomover")      # the answer path's codes that record nothing and leave the question standing: the frame stays open with the notice


def _when_ts(rec: dict[str, Any]) -> float:
    try:
        return float(rec.get("ts") or 0)
    except (TypeError, ValueError):
        return 0.0


def last_answer(r: dict[str, Any]) -> dict[str, Any] | None:
    """The latest recorded answer to a question on the item: a decision, never a comment, a Done or a note on a step, or a step the server ticked on a mail; None when there is none."""
    return next((a for a in reversed(_r.answers_of(r)) if a.get("kind") == "decision" and not a.get("step") and a.get("via") != "mail"), None)


def state_of(board: Any, r: dict[str, Any], token: str, was: str, since: float) -> tuple[str, Any]:
    """The frame's state of the item for a signed-in member, with what it draws: ("open", (question html, form html)), ("answered", the answer record), ("changed", None) or ("closed", None).
    `was` is the reference (model/ask_ref.py) of the question this frame first drew ("" when it has drawn none) and `since` when it was first drawn (epoch seconds): a refresh reads the state
    against them, a first load or a reload has neither question nor claim on an old one."""
    if r.get("status") != "completed" and _home.list_of(board.mod_of(r)) == _home.YOUR_MOVE:      # on his move, by the same rule as the home page's list
        ask = board.home_ask(r, token)
        if ask and (_r.open_options(r) or _r.yesno_options(r)):      # with cards to pick from
            return ("changed", None) if was and _r.question_ref(r) != was else ("open", ask)
    a = last_answer(r)
    if was:
        return ("answered", a) if a and _when_ts(a) > since else ("closed", None)
    meta = r.get("metadata") or {}
    if a and not meta.get("ask") and not meta.get(_askl.LEFT):      # an ask still stored, or one the server took off his move, is newer than the last answer: that answer is not what the item asks now
        return "answered", a
    return "closed", None


def _board_link(href: str, key: str) -> str:
    return f'<p class="aflink"><a href="{esc(href)}" target="_blank" rel="noopener">{esc(_t(key))}</a></p>'


def _answered_html(board: Any, r: dict[str, Any], a: dict[str, Any]) -> str:
    """The recorded answer: the question he answered, who answered and when, the card he picked and his note. Nothing in it can be pressed."""
    word = lambda k: str(a.get(k) or "").strip()
    out = []
    if word("ask"):
        out.append(f'<div class="ir-det"><span class="hnext hq">{board.md_line(_r.decide_words(word("ask")), r["gid"])}</span></div>')
    ts = _when_ts(a)
    out.append(f'<p class="afwho">{esc(_t("frame.answered_by", who=_members.recorded_by(a), when=board.when(ts) if ts > 0 else ""))}</p>')
    if word("choice"):
        line = word("choice_line")
        out.append('<div class="acards"><div class="acard afpick"><span class="adot" aria-hidden="true"></span><span class="abody">'
                   f'<span class="alab">{esc(_ol.pick_words(word("choice"), word("letter")))}</span>' + (f'<span class="adesc">{esc(line)}</span>' if line else "") + '</span></div></div>')
    if word("text"):
        out.append(f'<p class="aftext">{esc(word("text"))}</p>')
    return "".join(out)


def item_body(board: Any, r: dict[str, Any], state: str, what: Any) -> str:
    """The inside of the frame for a signed-in member's state."""
    if state == "open":
        q, form = what
        return f'<div class="ir-det"><span class="hnext hq">{q}</span>{board.home_draft_html(r)}</div><div class="ir-act">{form}</div>'
    if state == "answered":
        return _answered_html(board, r, what)
    return f'<p class="afline">{esc(_t("frame." + state))}</p>' + _board_link(_r.id_href(r["gid"]), "frame.open_board")


def signed_out_body(href: str) -> str:
    """Nothing of any item: a line and the link to the item on the board, in a new tab. The same for an item that exists and one that does not."""
    return f'<p class="afline">{esc(_t("frame.signed_out"))}</p>' + _board_link(href, "frame.signed_out_link")


def closed_body(href: str) -> str:
    return f'<p class="afline">{esc(_t("frame.closed"))}</p>' + _board_link(href, "frame.open_board")


def _notices() -> dict[str, list[str]]:
    """The notice of each code the answer path can say (the home page's wording where a code has one: the frame has no "below" either): {code: [class, text]}."""
    return {code: [v[0], _t(v[-1])] for code, v in _r.Board._SENT_KEYS.items()}


def page(body: str, *, key: str, state: str, href: str, origins: list[str], lang: str, theme: str, drawn: float, ref: str = "", channel: str = "") -> str:
    """The whole frame page, drawn in the request's language (the caller sets it, i18n.use(lang)). `key` is the item as the address names it (what the messages carry), `href` the board link the
    script falls back to, `channel` what two frames of one item share their pick and note over ("" = nothing to share), `theme` "dark", "light" or "" for the device's own."""
    data = {"item": key, "state": state, "ref": ref, "chan": channel, "drawn": f"{drawn:.6f}", "href": href, "origins": json.dumps(origins), "msgs": json.dumps(_notices()),
            "quiet": " ".join(_QUIET), "lines": json.dumps({"changed": _t("frame.changed"), "closed": _t("frame.closed"), "answered": _t("frame.sent"), "link": _t("frame.open_board")})}
    attrs = " ".join(f'data-{k}="{esc(v)}"' for k, v in data.items())      # everything the script reads is an escaped attribute: no value is written into script text
    font_css = str(_cfg.get("instance", "font_css") or "")
    out = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">'
           f'<base target="_blank"><title>{esc(_t("frame.title"))}</title>' + (f'<link rel="stylesheet" href="{esc(font_css)}">' if font_css else "") + _r._SST_HEAD
           + f'<style>{_r.Board._css()}{_CSS}</style><noscript><style>form.hanswer{{display:none}}</style></noscript></head><body class="aframe"><main id="aframe" {attrs}><div id="afbody">{body}</div><div id="afmsg" role="status" aria-live="polite"></div></main>'
           + f'<noscript><p class="afline">{esc(_t("frame.noscript"))}</p>{_board_link(href, "frame.open_board")}</noscript>'
           + _r._CARDS_JS + _r._SENDKEY_JS + _r._COPY_JS + _SCRIPT + '</body></html>')
    out = _r.apply_lang(out, lang)
    return out.replace("<html lang=", f'<html data-theme="{theme}" lang=', 1) if theme in ("dark", "light") else out      # with none, the board's stylesheet follows the device


# Over the board's own stylesheet: the page is the block alone, as tall as its content (the parent sizes the frame to it, so nothing here is measured against the viewport's height and nothing
# scrolls inside), and none of the board's fixed page furniture is drawn.
_CSS = """
html{scrollbar-gutter:auto}
body.aframe{margin:0;padding:0;display:flow-root}
body.aframe::before,body.aframe::after{display:none}
#aframe{display:flow-root;max-width:none;min-width:0;margin:0;padding:6px;overflow-wrap:anywhere}
#aframe .ir-det{margin-top:0}
#aframe .abox textarea{max-height:none;overflow:hidden}
@media(pointer:coarse){#aframe form.hanswer textarea{font-size:16px}}
.afline{margin:0 0 6px}.aflink{margin:0}.aflink a{display:inline-block;padding:6px 0;font-weight:500}
.afwho{margin:8px 0 6px;font-size:13px;color:var(--mut)}
#aframe .acards .afpick{border:2px solid var(--acc);background:var(--selbg);padding:9px 11px;cursor:default}
.afpick .adot{border-color:var(--acc)}.afpick .adot::after{content:"";width:8px;height:8px;border-radius:50%;background:var(--acc)}
.afpick .adesc{white-space:pre-line}
.aftext{margin:8px 0 0;white-space:pre-wrap}
#afmsg .isent{margin:8px 0 0}
"""

# The frame's script. What it holds: the state and what the parent is told of it (post: height, state, typing; only ever to a configured origin by name), the parent's two requests (refresh,
# theme; accepted only from window.parent at a configured origin), the send (the board's own answer path, asked for its code as JSON), the refresh (this page again, read against the question
# first drawn), and what two frames of one item share (BroadcastChannel on the board's origin: the pick, the note, a send under way and how it ended; only a person's own press or typing shares,
# never a field's `change`, which a box left for the other frame fires with what it held before that press). Nothing it posts to the parent or reads
# from it holds a word of the item, the answer or the token.
_SCRIPT = r"""<script>(function(){
var M=document.getElementById('aframe');if(!M)return;
var root=document.documentElement,framed=window.parent!==window;
function A(n){return M.getAttribute('data-'+n)||''}
function J(n,d){try{return JSON.parse(A(n))||d}catch(e){return d}}
var item=A('item'),since=A('drawn'),origins=J('origins',[]),msgs=J('msgs',{}),lines=J('lines',{}),quiet=A('quiet').split(' ');
var state=A('state'),was=state==='open'?A('ref'):'',typing=false,busy=false,mine=false,seq=0,last='',drafts={},bc=null,bcName='',watch=0;
function form(){return M.querySelector('form.hanswer')}
function box(f){return f&&f.querySelector('textarea')}
function isNote(t){return !!(t&&t.tagName==='TEXTAREA'&&M.contains(t))}
function post(){if(!framed)return;var m={source:'stackshot',kind:'answer-frame',v:1,item:item,height:Math.ceil(document.body.getBoundingClientRect().height),state:state,typing:typing},s=JSON.stringify(m);
if(s===last)return;last=s;origins.forEach(function(o){window.parent.postMessage(m,o)})}
function to(s){state=s;M.setAttribute('data-state',s);post()}
function grow(t){if(!t)return;t.style.height='auto';t.style.height=(t.scrollHeight+t.offsetHeight-t.clientHeight)+'px'}
function picked(f){var p=f.querySelector('input[name=choice]:checked');return p?p.value:''}
function put(f,d){[].forEach.call(f.querySelectorAll('input[name=choice]'),function(i){i.checked=i.value===d.pick});f._was=picked(f);
var t=box(f);if(t&&t.value!==d.note){t.value=String(d.note||'');grow(t)}if(window.ssCards)ssCards.sync(f)}
function keep(){var f=form();if(f&&A('ref'))drafts[A('ref')]={pick:picked(f),note:box(f).value}}
function say(cls,text){var m=M.querySelector('#afmsg');m.textContent='';if(text){var p=document.createElement('p');p.className='isent '+cls;p.textContent=text;m.appendChild(p)}post()}
function lock(on){var f=form();busy=on;if(!f)return;var b=f.querySelector('button[name=act]');
if(on)f.setAttribute('aria-busy','true');else f.removeAttribute('aria-busy');
[].forEach.call(f.querySelectorAll('input[name=choice],button'),function(x){x.disabled=on});box(f).readOnly=on;
if(b){if(on){if(!b.hasAttribute('data-label'))b.setAttribute('data-label',b.textContent);b.textContent=SST('js.answer.sending');b.setAttribute('aria-busy','true')}
else{if(b.hasAttribute('data-label'))b.textContent=b.getAttribute('data-label');b.removeAttribute('aria-busy')}}
if(!on&&window.ssCards)ssCards.sync(f)}
function tell(m){if(bc)try{bc.postMessage(m)}catch(e){}}
function share(){var f=form();if(f&&state==='open'&&!busy)tell({k:'edit',ref:A('ref'),pick:picked(f),note:box(f).value})}
function join(){var n=A('chan');if(n===bcName||!window.BroadcastChannel)return;if(bc)bc.close();bc=null;bcName=n;if(!n)return;
bc=new BroadcastChannel('stackshot-answer-frame:'+n);bc.onmessage=heard}
function hello(){if(state==='open')tell({k:'hello',ref:A('ref')})}
function heard(e){var d=e.data||{},f=form();if(!f||d.ref!==A('ref'))return;
if(d.k==='hello'){if(busy&&mine)tell({k:'sending',ref:d.ref,pick:picked(f),note:box(f).value});else if(picked(f)||box(f).value)share();return}
if(d.k==='edit'){if(state==='open'&&!busy){put(f,d);post()}return}
if(d.k==='sending'){if(state!=='open')return;put(f,d);say('','');lock(true);mine=false;to('sending');clearTimeout(watch);watch=setTimeout(release,75000);return}
if(d.k==='done'){clearTimeout(watch);finish(d.ref,d)}
if(d.k==='gone'){clearTimeout(watch);release()}}
function release(){if(state!=='sending'||mine)return;lock(false);to('open');refresh()}
function load(){var u=new URL(location.href);u.searchParams.set('since',since);if(was)u.searchParams.set('was',was);else u.searchParams.delete('was');
return fetch(u.href,{credentials:'same-origin',cache:'no-store',headers:{'Accept':'text/html'}}).then(function(r){if(r.status!==200&&r.status!==404)throw 0;return r.text()})
.then(function(t){var n=new DOMParser().parseFromString(t,'text/html').getElementById('aframe');if(!n||n.getAttribute('data-item')!==item)throw 0;return n})}
function show(n){var next=n.getAttribute('data-state'),ref=n.getAttribute('data-ref'),f=form();
if(next==='open'&&state==='open'&&ref===A('ref')&&f){var a=f.querySelector('input[name=token]'),b=n.querySelector('input[name=token]');if(a&&b)a.value=b.value;return}
keep();M.querySelector('#afbody').innerHTML=n.querySelector('#afbody').innerHTML;
['ref','chan','href'].forEach(function(k){M.setAttribute('data-'+k,n.getAttribute('data-'+k)||'')});
state=next;M.setAttribute('data-state',next);busy=false;
if(next==='open'){if(!was)was=ref;f=form();if(f&&drafts[ref])put(f,drafts[ref]);grow(box(f))}
join();document.dispatchEvent(new Event('stackshot:swapped'));typing=isNote(document.activeElement);post();hello()}
function refresh(){if(busy)return Promise.resolve();var s=++seq;return load().then(function(n){if(s===seq&&!busy){var before=state;show(n);return before!==state?state:''}},function(){})}
function fall(code){var s=code==='decision'?'answered':code==='stale'||code==='stalenote'||code==='askedback'?'changed':'closed',b=M.querySelector('#afbody');b.textContent='';
var p=document.createElement('p');p.className='afline';p.textContent=lines[s]||'';b.appendChild(p);
if(s!=='answered'){var q=document.createElement('p');q.className='aflink';var a=document.createElement('a');a.href=A('href');a.target='_blank';a.rel='noopener';a.textContent=lines.link||'';q.appendChild(a);b.appendChild(q)}
to(s)}
function finish(ref,res){if(ref!==A('ref')||!form())return;
if(res.why){lock(false);to('open');say('warn',SST('js.answer.nothing_sent',{why:res.why}));
refresh().then(function(s){if(s&&s!=='open'&&s!=='signed_out')say('','')});return}
var m=msgs[res.code]||['warn',''];
if(quiet.indexOf(res.code)>=0){lock(false);to('open');say(m[0],m[1]);return}
delete drafts[ref];var s=++seq;
load().then(function(n){if(s!==seq)return;var f=form();if(f){box(f).value='';put(f,{pick:'',note:''})}lock(false);show(n);delete drafts[ref];say(m[0],m[1])},
function(){if(s!==seq)return;busy=false;say(m[0],m[1]);fall(res.code)})}
function send(f,submitter){var ref=A('ref'),data=new URLSearchParams(new FormData(f)),ctl=window.AbortController?new AbortController():null,timer=ctl&&setTimeout(function(){ctl.abort()},60000);
if(!picked(f)&&!box(f).value.trim())return;
data.set('act','answer');seq++;say('','');tell({k:'sending',ref:ref,pick:picked(f),note:box(f).value});mine=true;lock(true);to('sending');
fetch(f.getAttribute('action'),{method:'POST',body:data,credentials:'same-origin',cache:'no-store',headers:{'Accept':'application/json'},signal:ctl?ctl.signal:undefined})
.then(function(r){return r.text().then(function(t){var j=null;try{j=JSON.parse(t)}catch(e){}if(r.ok&&j&&typeof j.sent==='string')return {code:j.sent};
t=String(t||'').replace(/\s+/g,' ').trim();return {why:!r.ok&&t&&t.length<400&&!/^</.test(t)?t:SST('js.answer.bad_reply',{what:r.ok?SST('js.answer.unexpected_page'):r.status})}})},
function(){return {why:SST('js.answer.no_answer')}})
.then(function(res){clearTimeout(timer);mine=false;tell({k:'done',ref:ref,code:res.code,why:res.why});finish(ref,res)})}
document.addEventListener('submit',function(e){var f=e.target;if(f!==form())return;e.preventDefault();if(!busy&&state==='open')send(f,e.submitter)});
document.addEventListener('input',function(e){if(!M.contains(e.target))return;if(isNote(e.target))grow(e.target);share();post()});
document.addEventListener('click',function(e){var t=e.target;if(t&&t.matches&&t.matches('form.hanswer input[name=choice]')){share();post()}});
function focus(on){if(typing!==on){typing=on;post()}}
document.addEventListener('focusin',function(e){focus(isNote(e.target))});
document.addEventListener('focusout',function(e){if(isNote(e.target))focus(false)});
window.addEventListener('message',function(e){if(!framed||e.source!==window.parent||origins.indexOf(e.origin)<0)return;
var d=e.data;if(!d||typeof d!=='object'||typeof d.source!=='string'||d.kind!=='answer-frame'||d.v!==1)return;
if(d['do']==='refresh')refresh();else if(d['do']==='theme'&&(d.theme==='dark'||d.theme==='light')){root.setAttribute('data-theme',d.theme);post()}});
function back(){if(state==='signed_out'&&document.visibilityState!=='hidden')refresh()}
window.addEventListener('focus',back);document.addEventListener('visibilitychange',back);window.addEventListener('pageshow',function(e){if(e.persisted)back()});
window.addEventListener('pagehide',function(){if(busy&&mine)tell({k:'gone',ref:A('ref')})});
window.addEventListener('resize',function(){grow(box(form()));post()});
document.addEventListener('toggle',post,true);window.addEventListener('load',post);if(document.fonts&&document.fonts.ready)document.fonts.ready.then(post);
if(window.ResizeObserver)new ResizeObserver(function(){post()}).observe(document.body);
grow(box(form()));join();post();hello()})();</script>"""
