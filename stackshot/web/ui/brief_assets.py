"""brief_assets.py — the style and the script of the item brief (ui/brief.py), and the panel the home page opens it in.

The brief is a short view of one item: what it asks, enough to decide, and the answer box. The home page shows it in a panel (on the right from 800 px wide, a bottom sheet below that);
/items/<key>/brief shows it as a page of its own. The renderer (ui/render.py) puts CSS in every page's style, PANEL and JS on the home page.
"""
from __future__ import annotations

import html as _html

from stackshot.web.i18n import t as _t
from stackshot.web.ui import PREFIX

_NARROW = "(max-width:799.98px)"      # the complement of min-width:800px, the width the summary panel docks from


def panel_html() -> str:
    """The home page's panel, empty and hidden, drawn once outside the blocks the live refresh swaps; its bar's words are in the page's language."""
    def btn(act: str, key: str, glyph: str, hint: str = "") -> str:
        word = _html.escape(_t(key))
        return f'<button type="button" class="b" data-bact="{act}" aria-label="{word}" title="{word}{hint}">{glyph}</button>'
    return ('<div id="brief-scrim" hidden></div><aside id="brief" role="dialog" aria-labelledby="brief-title" tabindex="-1" hidden>'
            '<div class="brief-top"><span class="bgrab" aria-hidden="true"></span><div class="brief-bar">'
            + btn("prev", "brief.prev", "&#8249;", " (k)") + btn("next", "brief.next", "&#8250;", " (j)")
            + f'<a class="b" data-bact="full">{_html.escape(_t("brief.full"))}</a>'
            + btn("close", "brief.close", "&#215;", " (Esc)")
            + '</div></div><div id="brief-main"></div></aside><div id="brief-toast" role="status" hidden></div>')


CSS = """
:root{--bw:min(560px,48vw)}
/* the row's button is a chip of its own, not a `.b` button: small to look at, a full target for a finger */
.bopen{float:right;position:relative;margin:0 0 0 8px;padding:1px 10px;font:inherit;font-size:13px;line-height:20px;white-space:nowrap;border:1px solid var(--line);border-radius:999px;background:none;color:var(--mut);cursor:pointer}
.bopen:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
@media(hover:hover){.bopen:hover{border-color:var(--acc);color:var(--fg)}}
@media(pointer:coarse){.bopen::after{content:'';position:absolute;left:0;right:0;top:50%;height:44px;transform:translateY(-50%)}}
li.irow.hrow.is-open{background:var(--selbg);box-shadow:0 0 0 2px var(--acc)}
li.irow.hrow.sent>.ir-top,li.irow.hrow.sent>.ir-det{opacity:.45}
li.irow.hrow>.bnote{clear:both}
.bdismiss,.bnote .bdismiss,.aerr .bdismiss{margin-left:6px;font-size:13px}
#brief{position:fixed;z-index:30;top:0;right:0;bottom:0;width:var(--bw);display:flex;flex-direction:column;background:var(--bg);border-left:1px solid var(--line);box-shadow:-10px 0 24px -18px rgba(0,0,0,.45);outline:0}
#brief[hidden],#brief-scrim[hidden],#brief-toast[hidden]{display:none}
.brief-top{flex:none;background:var(--card)}
.bgrab{display:none}
.brief-bar{display:flex;align-items:center;justify-content:flex-end;gap:6px;padding:10px 16px 0}
.brief-bar .b{flex:none;min-height:32px;padding:3px 9px;white-space:nowrap}
@media(pointer:coarse){.brief-bar .b{min-width:44px;min-height:44px}}
#brief-main{flex:1 1 auto;min-height:0;display:flex;flex-direction:column}
.bload{margin:0;padding:20px 16px;color:var(--mut)}
.bfail{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:20px 16px}
.bfail>p{flex:1 0 100%;margin:0}
.bfail a.b{text-decoration:none}
.bchanged{flex:none;display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:8px 16px;border-bottom:1px solid var(--warn);background:var(--card);font-size:13px}
.bitem{flex:1 1 auto;min-height:0;display:flex;flex-direction:column}
.bhead{flex:none;padding:4px 16px 10px;border-bottom:1px solid var(--line);background:var(--card)}
.bitem .btitle{margin:6px 0 0;font-size:13px;font-weight:400;line-height:20px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.btitle a{color:var(--mut);text-decoration:underline;text-decoration-color:var(--ibd);text-underline-offset:3px}
.btitle a:focus-visible{outline:2px solid var(--acc);outline-offset:-2px}
.bwhole .btitle{white-space:normal}
@media(pointer:coarse){.bitem .btitle{margin:-4px 0 -10px;padding:15px 0}.btitle a{padding:15px 0}}
.bq{display:flex;align-items:flex-start;gap:4px;margin:0;font-size:16px;font-weight:600;line-height:1.45}
.bq>span{min-width:0}
.bq>.xp{flex:none;margin-top:-2px}
.bstate{margin:0 0 14px;font-size:14px;color:var(--mut)}
.bitem .istep{display:flex;align-items:flex-start;gap:4px}
.bitem .istep>.istepbody{flex:1 1 auto;min-width:0;margin-top:0}
.bitem .istep>.xp{flex:none;margin-top:4px}
@media(pointer:coarse){.bq>.xp{margin-top:-10px}.bitem .istep>.xp{margin-top:-4px}}
.bitem .xp-pop{max-height:50vh;overflow-y:auto;overscroll-behavior:contain;white-space:pre-line}
.bbody{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;overflow-y:auto;overscroll-behavior:contain;padding:12px 16px 0;overflow-wrap:anywhere}
.bbody>*{flex:none;min-width:0}
.bbody::after{content:'';order:1;flex:none;height:20px}
.bitem .iask .breco{margin:6px 0 0;font-size:14px;line-height:1.5}
.bitem .iask .iopts{margin-top:8px}
.bsent .bnext,.bsent .bretry{margin:0 8px 12px 0}
.bheld{margin:0 0 14px}
.bheld .dhead{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.bheld .dhead button.copy{margin-left:0}
.bbody>form.ianswer[data-cards]{display:contents}
.bbody>form.ianswer[data-cards]>.acards{margin-bottom:14px}
.bbody .bfoot,.bbody>form.ianswer:not([data-cards]){order:2;position:sticky;bottom:0;z-index:2;margin:auto -16px 0;padding:8px 16px calc(10px + env(safe-area-inset-bottom));border:0;border-top:2px solid var(--line);border-radius:0;background:var(--card)}
.bitem .bfoot label,.bbody>form.ianswer:not([data-cards])>label{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.bitem form.ianswer textarea{height:38px;min-height:38px}
.bitem form.ianswer textarea:focus,.bitem form.ianswer textarea:not(:placeholder-shown){height:84px}
@media(pointer:coarse){.bitem .abox textarea:placeholder-shown:not(:focus){height:38px!important}.bitem form.ianswer .abox textarea:focus{min-height:84px}}
.bitem .abtns,.bitem .abtns-send{align-items:center}
.bitem .ahint{display:none}
.bitem.justsent form[data-comment-only]{display:none}
#brief-toast{position:fixed;left:50%;bottom:24px;z-index:32;transform:translateX(-50%);display:flex;flex-wrap:wrap;align-items:center;gap:8px;width:max-content;max-width:calc(100vw - 32px);box-sizing:border-box;margin:0;padding:10px 16px;border:1px solid var(--ibd);border-radius:8px;background:var(--card);color:var(--fg);font-size:14px;box-shadow:0 6px 24px rgba(0,0,0,.22);overflow-wrap:anywhere}
#brief-scrim{position:fixed;inset:0;z-index:29;background:rgba(0,0,0,.42)}
body.brief-open::after{display:none}
@media(min-width:800px){body.brief-open #layout,body.panel-pin.brief-open #layout{padding-right:var(--bw)}
body.brief-open #panel,body.brief-open #panel-edge,body.brief-open #panel-scrim,body.brief-open #panel-open,body.brief-open header.top .theme,body.brief-open .fab,body.brief-open #totop{visibility:hidden}
#brief-scrim{display:none}}
@media__NARROW__{body.brief-open #panel-open,body.brief-open header.top .theme{visibility:hidden}
#brief{top:auto;left:0;width:auto;height:92vh;height:92dvh;border-left:0;border-radius:16px 16px 0 0;overflow:hidden}
.brief-top,#brief .bhead{touch-action:none}
.bgrab{display:block;width:44px;height:5px;margin:0 auto;border-radius:3px;background:var(--ibd);position:relative;top:6px}
.brief-bar{flex-wrap:wrap;gap:4px;padding:12px 8px 0}
.brief-bar .b{min-width:44px;min-height:44px;padding:3px 8px}
.bitem form.ianswer textarea{font-size:16px}
.bitem .bfoot{display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:8px;align-items:center}
.bitem .bfoot>*{grid-column:1/-1}
.bitem .bfoot>.abox{grid-column:1}
.bitem .bfoot>.abtns-send{grid-column:2;flex-wrap:nowrap;margin:0}
html.sheet,html.sheet body{overflow:hidden}}
main.briefpage{overflow-wrap:anywhere}
#brief-page>.bitem{margin-top:12px;max-width:760px;border:1px solid var(--line);border-radius:12px}
#brief-page>.bchanged{max-width:760px;box-sizing:border-box}
#brief-page .bhead{border-radius:12px 12px 0 0}
#brief-page .bbody{flex:none;overflow:visible}
#brief-page .bfoot,#brief-page .bbody>form.ianswer:not([data-cards]){border-radius:0 0 12px 12px}
body:has(main.briefpage) .fab,body:has(main.briefpage) #totop{display:none}
.bbody .iask,.bbody .draft{margin-bottom:14px}.bbody .isent{margin-bottom:12px}
""".replace("__NARROW__", _NARROW)

# One script for both places. On the home page it opens the brief of a clicked row in the panel (the address becomes ?item=<key>: Back, Escape and the close button
# close it) and says when the open item changed under it. In both places an answer is the page's own form, posted to the one answer route with `Accept: application/json`;
# the brief read again with ?sent=<code> says what happened, and is drawn in place. Nothing here leaves the page by itself: a brief that cannot be read says so, with a link.
#
# What he has picked or written and not sent is a draft, one per item (D), kept in sessionStorage so it comes back after the detail view, the full screen view or a reload;
# where the browser keeps nothing, leaving asks first. A draft's fields: c the picked value, l that card's words, r the question the pick was made on (the form's ref),
# t the note, f the kind of box the note was written in (ask, step, comment), h a note that no longer fits the item's box (offered, never put in another kind of box by
# itself), x the words of a pick that was dropped because the question changed, e why the last send failed, s a send under way.
JS = r"""(function(){
if(!window.fetch||!window.DOMParser||!window.URLSearchParams)return;
var P=document.getElementById('brief'),FULL=document.getElementById('brief-page'),V=P?document.getElementById('brief-main'):FULL;
if(!V)return;
var KEY=/^([a-z][0-9]+|[1-9][0-9]*|board-tmp-[a-z0-9-]*[a-z0-9]-[1-9][0-9]*)$/,STORE='ss-brief-drafts',LIMIT=30000,
D={},SENDING={},ANSWERED={},stored=true,armed=false,cur=null,toast=document.getElementById('brief-toast'),tt=0;
function $(s,r){return (r||document).querySelector(s)}
function all(s,r){return [].slice.call((r||document).querySelectorAll(s))}
function page(k){return '@ROOT@/items/'+k}
function el(tag,cls,text){var e=document.createElement(tag);if(cls)e.className=cls;if(text)e.textContent=text;return e}
function btn(cls,text,fn){var b=el('button',cls,text);b.type='button';if(fn)b.addEventListener('click',fn);return b}
function link(k,cls,text){var a=el('a',cls,text);a.setAttribute('href',page(k));return a}
function load(url){var c=window.AbortController?new AbortController():null,t=c?setTimeout(function(){c.abort()},15000):0;
return fetch(url,{cache:'no-store',credentials:'same-origin',headers:{'Accept':'text/html'},signal:c?c.signal:undefined})
.then(function(r){if(!r.ok)throw 0;return r.text()}).then(function(x){clearTimeout(t);var a=new DOMParser().parseFromString(x,'text/html').querySelector('article.bitem');if(!a)throw 0;return a},function(e){clearTimeout(t);throw e})}
// ---- the rows of the home page
function keyOf(li){var a=li&&$('a.ir-link',li),m=a&&/\/items\/([^\/?#]+)$/.exec(a.getAttribute('href')||'');return m&&KEY.test(m[1])?m[1]:''}
function rows(){return all('li.irow.hrow').filter(function(li){return li.getClientRects().length&&keyOf(li)})}
function rowFor(k){return all('li.irow.hrow').filter(function(li){return keyOf(li)===k})[0]||null}
function rowForm(li){return li?$('form.hanswer',li):null}
// ---- a form and its draft
function form(r){return r?$('form.ianswer',r):null}
function boxForm(){var a=cur&&$('article.bitem',V);return a?form(a):null}
function drawn(f){return !!f&&f.matches('[data-cards],[data-step]')}
function family(f){return f.hasAttribute('data-step')?'step':f.hasAttribute('data-cards')||$('button[value=answer]',f)?'ask':'comment'}
function refOf(f){var x=$('input[name=ref]',f);return x?x.value:''}
function chosen(f){return $('input[name=choice]:checked',f)}
function noteOf(f){var t=$('textarea',f);return t?t.value:''}
function label(p){var c=p.closest('.acard'),l=c&&$('.alab',c),k=l&&$('.akey',l);return l?(k?k.textContent+' · '+l.textContent.slice(k.textContent.length):l.textContent):p.value}
function sync(f){if(window.ssCards&&drawn(f))ssCards.sync(f)}
function entry(k){return D[k]||(D[k]={})}
// what no longer fits the box is set aside, never dropped: the note is held, the pick is named
function stash(d){if(d.t){d.h=d.h&&d.h!==d.t?d.h+'\n\n'+d.t:d.t;d.t=''}if(d.c){d.x=d.l||d.c;d.c=''}d.f=''}
function holds(d){return !!(d.c||d.t||d.h||d.x||d.e||d.s)}
function read(){try{var v=JSON.parse(sessionStorage.getItem(STORE)||'{}');return v&&typeof v==='object'?v:{}}catch(e){return null}}
function save(){Object.keys(D).forEach(function(k){if(!holds(D[k]))delete D[k]});
if(stored)try{if(Object.keys(D).length)sessionStorage.setItem(STORE,JSON.stringify(D));else sessionStorage.removeItem(STORE)}catch(e){stored=false}
guard()}
// leaving is asked about only when it would lose something: a send from the brief is under way, or this browser keeps no draft and there is one
function warn(e){e.preventDefault();e.returnValue=''}
function guard(){var need=Object.keys(SENDING).some(function(k){return !SENDING[k].row})||(!stored&&Object.keys(D).some(function(k){var d=D[k];return !SENDING[k]&&!!(d.c||d.t||d.h)}));
if(need!==armed){armed=need;window[need?'addEventListener':'removeEventListener']('beforeunload',warn)}}
// the one place a field he touched goes into the draft
function capture(k,f,t){var fam=family(f),d=entry(k);if(d.f&&d.f!==fam)stash(d);
if(t.tagName==='TEXTAREA')d.t=t.value;else{var p=chosen(f);d.c=p?p.value:'';d.l=p?label(p):'';d.r=refOf(f);delete d.x}
d.f=d.c||d.t?fam:'';save()}
// the draft into a form. `fresh`: the form has just arrived from the server, so what no longer fits it is set aside; a form already on the page only shows what fits
function put(k,f,fresh){var d=D[k];if(!f){if(fresh&&d){stash(d);save()}return}
if(!d){if(fresh)return;d={}}
var ref=refOf(f),radios=all('input[name=choice]',f);
if(fresh){if(d.f&&d.f!==family(f))stash(d);else if(d.c&&((ref&&d.r&&ref!==d.r)||!radios.some(function(i){return i.value===d.c}))){d.x=d.l||d.c;d.c=''}save()}
var mine=!d.f||d.f===family(f),t=$('textarea',f),v=(mine&&d.t)||'';
if(t&&t.value!==v)t.value=v;
radios.forEach(function(i){i.checked=mine&&!!d.c&&i.value===d.c&&(!ref||!d.r||ref===d.r)});
var p=chosen(f);f._was=p?p.value:'';sync(f)}
function words(d,f){var o=[];if(d&&d.e)o.push(d.e);if(d&&d.x)o.push(SST(f&&f.matches('[data-cards]')?'js.brief.repick':'js.brief.pick_gone',{what:d.x}));return o}
function tellIn(box,k,lines){box.textContent=lines.join(' ')+' ';var b=btn('b bdismiss',SST('js.brief.dismiss'));b.setAttribute('data-dismiss',k);box.appendChild(b)}
// what the brief says about the open item's draft: under Send where there is a box, else at the top, with the note that fits no box
function notes(){var art=cur&&$('article.bitem',V);if(!art)return;var k=cur.k,f=form(art),d=D[k],E=f&&$('.aerr',f),lines=words(d,f),sig=JSON.stringify([!!f,lines,d&&d.h||'']);
if(art._said===sig)return;art._said=sig;var old=$('.bheld',art);if(old)old.remove();
if(E){if(lines.length)tellIn(E,k,lines);else E.textContent='';E.hidden=!lines.length}
if(!d||!(d.h||(!E&&lines.length)))return;var box=el('div','bheld');
if(!E&&lines.length){var p=el('p','isent warn');p.setAttribute('role','alert');tellIn(p,k,lines);box.appendChild(p)}
if(d.h){var dr=el('div','draft'),head=el('div','dhead'),pre=el('pre');head.appendChild(el('b','dlab',SST('js.brief.unsent')));head.appendChild(btn('b copy',SST('js.copy')));
if(f){var u=btn('b buse',SST('js.brief.use_held'));u.setAttribute('data-use',k);head.appendChild(u)}
var x=btn('b bdrop',SST('js.brief.discard'));x.setAttribute('data-discard',k);head.appendChild(x);pre.appendChild(el('code','',d.h));dr.appendChild(head);dr.appendChild(pre);box.appendChild(dr)}
var body=$('.bbody',art),s=$('.bsent',body);body.insertBefore(box,s?s.nextSibling:body.firstChild)}
function rowNote(k){var li=rowFor(k);if(!li)return;var d=D[k],lines=words(d,rowForm(li));if(d&&d.h)lines.push(SST('js.brief.held_row'));var p=$('.bnote',li),sig=lines.join(' ');
if(!sig){if(p)p.remove();return}
if(!p){p=el('p','isent warn bnote');p.setAttribute('role','status');li.appendChild(p)}
if(p._said!==sig){p._said=sig;tellIn(p,k,lines)}}
// every form of an item with a send under way is shut, wherever it is drawn, until the reply
function lock(f,v){if(f.hasAttribute('data-lock'))return;f.setAttribute('data-lock','');f.setAttribute('aria-busy','true');
all('button[name=act]',f).forEach(function(b){b.disabled=true;if(!b.hasAttribute('data-spent'))b.setAttribute('data-spent','lock');
if(b.value===v){b._label=b.innerHTML;b.setAttribute('aria-busy','true');b.textContent=SST('js.answer.sending')}})}
function unlock(f){if(!f.hasAttribute('data-lock'))return;f.removeAttribute('data-lock');f.removeAttribute('aria-busy');var tk=$('input[name=token]',f);
all('button[name=act]',f).forEach(function(b){if(b.getAttribute('data-spent')==='lock'){b.removeAttribute('data-spent');b.disabled=!(tk&&tk.value)}
if(b._label!==undefined){b.innerHTML=b._label;delete b._label;b.removeAttribute('aria-busy')}});sync(f)}
function lockAll(){var l=[],f=boxForm();if(f)l.push([cur.k,f]);all('li.irow.hrow').forEach(function(li){var r=rowForm(li),k=keyOf(li);if(r&&k)l.push([k,r])});
l.forEach(function(p){var s=SENDING[p[0]];if(s)lock(p[1],s.v);else unlock(p[1])})}
// the draft changed by something other than typing: say it everywhere the item shows
function both(k){if(cur&&cur.k===k){var f=boxForm();if(f)put(k,f,false);notes()}var r=rowForm(rowFor(k));if(r&&D[k])put(k,r,false);rowNote(k)}
// ---- sending
function noticeOf(code,i){try{return JSON.parse(document.getElementById('sent-notes').getAttribute('data-notes'))[code][i]}catch(e){return i?code:''}}
// no reply (in time, or at all) and a server that failed both leave it unknown whether the answer was recorded, and say so
function post(url,data,done,fail){var c=window.AbortController?new AbortController():null,over=false,t=setTimeout(function(){if(c)c.abort();end(fail,SST('js.brief.unsure'))},LIMIT);
function end(fn,v){if(over)return;over=true;clearTimeout(t);fn(v)}
fetch(url,{method:'POST',body:data,credentials:'same-origin',cache:'no-store',headers:{'Accept':'application/json'},signal:c?c.signal:undefined})
.then(function(r){return r.text().then(function(x){var j=null;try{j=JSON.parse(x)}catch(e){}
if(r.ok&&j&&typeof j.sent==='string'&&j.sent)return end(done,j.sent);
if(r.status>=500)return end(fail,SST('js.brief.unsure'));
x=String(x||'').replace(/\s+/g,' ').trim();end(fail,SST('js.answer.nothing_sent',{why:!r.ok&&x&&x.length<400&&x.charAt(0)!=='<'?x:SST('js.answer.bad_reply',{what:r.ok?SST('js.answer.unexpected_page'):r.status})}))})})
.catch(function(){end(fail,SST('js.brief.unsure'))})}
function failure(k,why){var d=entry(k);d.e=why;delete d.s;save();notes();rowNote(k);if(P&&!(cur&&cur.k===k))tell(k,why)}
function send(f,b){var k=cur.k,art=f.closest('article.bitem');if(SENDING[k])return;
var data=new URLSearchParams(new FormData(f));if(b&&b.name)data.append(b.name,b.value);
var p=chosen(f),snap={c:p?p.value:'',t:noteOf(f),rec:(art.getAttribute('data-recorded')||'').split(' '),quiet:(art.getAttribute('data-keep')||'').split(' ')};
var d=entry(k);if(d.f&&d.f!==family(f))stash(d);d.t=snap.t;d.c=snap.c;d.l=p?label(p):'';d.r=refOf(f);d.f=d.c||d.t?family(f):'';d.s=1;delete d.e;
SENDING[k]={v:b?b.value:''};cur.n++;save();lockAll();notes();rowNote(k);
post(f.getAttribute('action'),data,function(code){answered(k,code,snap)},function(why){delete SENDING[k];guard();lockAll();failure(k,why);if(cur&&cur.k===k)check()})}
// the board replied with a code: a code that recorded something ends the draft (what he typed meanwhile stays), any other keeps all of it. Then the item is read again.
function answered(k,code,snap){var rec=snap.rec.indexOf(code)>=0,d=entry(k);delete d.s;
if(rec){if(d.t===snap.t)d.t='';if(d.c===snap.c)d.c='';delete d.e;delete d.x;if(!d.c&&!d.t)d.f=''}
save();
load(page(k)+'/brief?sent='+encodeURIComponent(code)).then(function(a){delete SENDING[k];guard();
var s=$('.bsent',a),ok=!!s&&s.getAttribute('data-ok')==='1',said=s?s.textContent:noticeOf(code,1),here=!!cur&&cur.k===k;
if(ok){ANSWERED[k]=1;rowSent(k,said)}else if(rec)rowReset(k);
lockAll();
if(here&&snap.quiet.indexOf(code)>=0)failure(k,said);
else if(here){cur.n++;cur.sent=ok?s.cloneNode(true):null;cur.sentFp=a.getAttribute('data-fp')||'';render(a);show()}
else if(!rec)failure(k,said);
rowNote(k);if(!ok)window.dispatchEvent(new Event('focus'))},      // refused: the row is behind, so ask for the lists now; a sent one stays dimmed until their next refresh
function(){delete SENDING[k];guard();lockAll();
if(rec){ANSWERED[k]=1;rowSent(k,SST('js.brief.sent'));if(cur&&cur.k===k)unread(k)}
else failure(k,SST('js.answer.nothing_sent',{why:noticeOf(code,1)}));
window.dispatchEvent(new Event('focus'))})}
function rowReset(k){var f=rowForm(rowFor(k));if(f){f.reset();sync(f);if(D[k])put(k,f,false)}}
function rowSent(k,said){var li=rowFor(k);if(!li)return;li.classList.add('sent');var f=rowForm(li);if(f){f.reset();f.hidden=true;f.removeAttribute('data-gid')}
if(!$('.bsentline',li)){var p=el('p','isent ok bsentline',said);li.appendChild(p)}}
// ---- the brief itself
function show(){if(P)P.focus({preventScroll:true});else window.scrollTo(0,0)}
function nextButton(s){if(P&&!$('.bnext',s))s.appendChild(btn('b bnext',SST('js.brief.next')))}
function render(a,keep){var k=cur.k,b=$('.bbody',V),y=keep&&b?b.scrollTop:0,had=!!P&&P.contains(document.activeElement),n=document.importNode(a,true);
V.innerHTML='';V.appendChild(n);cur.fp=n.getAttribute('data-fp')||'';
var f=form(n);if(cur.sent&&cur.fp!==cur.sentFp&&drawn(f))cur.sent=null;      // the item asks again: the last answer's notice goes
put(k,f,true);if(f)sync(f);
if(cur.sent){n.classList.add('justsent');var s=$('.bsent',n),into=$('.bbody',n);if(!s){s=cur.sent.cloneNode(true);into.insertBefore(s,into.firstChild)}nextButton(s)}
lockAll();notes();var r=rowForm(rowFor(k));if(r&&D[k])put(k,r,false);rowNote(k);
$('.bbody',n).scrollTop=y;if(had&&!P.contains(document.activeElement))P.focus({preventScroll:true});
document.dispatchEvent(new Event('stackshot:inserted'));
document.dispatchEvent(new Event('stackshot:redrawn'))}      // a "?" left open stays open on the markup that came; one of another item is forgotten
// recorded, but the item could not be read again: say so where the box was
function unread(k){var art=$('article.bitem',V);if(!art)return;var f=form(art);if(f)f.remove();var body=$('.bbody',art),s=el('div','bsent'),p=el('p','isent ok',SST('js.brief.sent_unread')+' ');
s.setAttribute('data-ok','1');p.setAttribute('role','status');p.appendChild(link(k,'',SST('js.brief.open_page')));s.appendChild(p);s.appendChild(btn('b bretry',SST('js.brief.retry'),latest));nextButton(s);
body.insertBefore(s,body.firstChild);cur.fp='unread';
var done=el('div','bsent');done.setAttribute('data-ok','1');done.appendChild(el('p','isent ok',SST('js.brief.sent')));cur.sent=done;cur.sentFp='';      // once the item can be read, it still says Sent
notes();show()}
function banner(text){var old=$('.bchanged',V);if(old)old.remove();var n=el('div','bchanged');n.setAttribute('role','status');n.appendChild(el('span','',text));n.appendChild(btn('b warn',SST('js.brief.show_latest'),latest));V.insertBefore(n,V.firstChild)}
// each read has a number: only the newest one is drawn, so an older one cannot put the item back as it was
function latest(){var me=cur;if(!me)return;var n=++me.n;load(page(me.k)+'/brief').then(function(a){if(cur===me&&me.n===n)render(a,true)},function(){if(cur===me&&me.n===n)banner(SST('js.brief.fail_load'))})}
// the lists moved on: read the open item again; with nothing half-written it is drawn anew, else a line says it changed and the draft stays
function check(){var me=cur;if(!me||!me.fp||SENDING[me.k])return;var n=++me.n;load(page(me.k)+'/brief').then(function(a){if(cur!==me||me.n!==n||SENDING[me.k])return;var old=$('.bchanged',V);
if(a.getAttribute('data-fp')===me.fp){if(old)old.remove();return}
var f=boxForm(),at=document.activeElement,typing=!!f&&f.contains(at)&&at.tagName==='TEXTAREA',d=D[me.k];
if(!(d&&(d.c||d.t))&&!typing){render(a,true);return}
if(!old)banner(SST('js.brief.changed'))},function(){})}
V.addEventListener('submit',function(e){var f=e.target;if(!f.matches('form.ianswer')||e.submitter===undefined)return;e.preventDefault();send(f,e.submitter)});
function typed(e){var t=e.target;if(!t||!t.matches||!t.form)return;var radio=t.matches('input[name=choice]'),text=t.matches('textarea[name=text]');
if(!((radio&&e.type!=='input')||(text&&e.type==='input')))return;
var f=t.form,k='',inside=V.contains(f);if(inside)k=cur?cur.k:'';else if(f.matches('form.hanswer'))k=keyOf(f.closest('li.irow.hrow'));if(!k)return;
capture(k,f,t);
// the row and the brief are one draft: what is picked or written in either shows in the other
var other=inside?rowForm(rowFor(k)):cur&&cur.k===k?boxForm():null;if(other)put(k,other,false);notes();rowNote(k)}
['input','change','click'].forEach(function(n){document.addEventListener(n,typed)});
document.addEventListener('click',function(e){var b=e.target.closest&&e.target.closest('[data-dismiss],[data-use],[data-discard]');if(!b)return;e.preventDefault();
var k=b.getAttribute('data-dismiss')||b.getAttribute('data-use')||b.getAttribute('data-discard'),d=D[k];if(!d)return;
if(b.hasAttribute('data-dismiss')){delete d.e;delete d.x}
else if(b.hasAttribute('data-discard'))delete d.h;
else{var f=cur&&cur.k===k?boxForm():null,t=f&&$('textarea',f);if(!t||SENDING[k])return;var held=d.h;delete d.h;t.value=t.value?t.value+'\n\n'+held:held;capture(k,f,t);sync(f)}
save();both(k)});
// ---- the drafts a page starts with
try{sessionStorage.setItem(STORE+'-probe','1');sessionStorage.removeItem(STORE+'-probe')}catch(e){stored=false}
D=(stored&&read())||{};
// a row's own Send leaves the page and comes back as ?sent=<code>&item=<key>: a code that recorded something ends that draft
if(P){var q0=new URLSearchParams(location.search),sk=q0.get('sent'),si=q0.get('item');
if(sk&&si&&D[si]){var d0=D[si];delete d0.s;if(sk==='askedback'||noticeOf(sk,0)==='ok'){d0.t='';d0.c='';d0.f='';delete d0.e;delete d0.x}}}
// a send that never came back to a page: it may have been recorded
function lost(){Object.keys(D).forEach(function(k){if(D[k].s&&!SENDING[k]){delete D[k].s;D[k].e=SST('js.brief.was_sending')}});save()}
lost();
if(!P){var art=$('article.bitem',FULL);if(art){cur={k:art.getAttribute('data-key'),fp:art.getAttribute('data-fp')||'',sent:null,sentFp:'',n:0};var first=form(art);
put(cur.k,first,true);if(first)sync(first);lockAll();notes()}
if(/[?&]sent=/.test(location.search)&&history.replaceState)history.replaceState(history.state,'',location.pathname);
return}
// ---- the panel
var scrim=$('#brief-scrim'),root=document.documentElement,body=document.body,MQ=matchMedia('__NARROW__'),homeY=0,last=null,inerted=[],drag=null;
function pills(){all('li.irow.hrow').forEach(function(li){if($('.bopen',li)||!keyOf(li))return;var p=$('.ir-proj',li);if(!p){p=document.createElement('div');p.className='ir-proj';li.insertBefore(p,li.firstChild)}
var b=btn('bopen',SST('js.brief.open'));p.appendChild(b)})}
function mark(){all('li.irow.is-open').forEach(function(li){li.classList.remove('is-open')});var li=cur&&rowFor(cur.k);if(li)li.classList.add('is-open')}
// the sheet is modal: the rest of the page is inert under it. The panel on a wide screen is not, the lists stay in use beside it
function lay(){var on=!!cur,n=on&&MQ.matches;root.classList.toggle('sheet',n);scrim.hidden=!n;if(n)P.setAttribute('aria-modal','true');else P.removeAttribute('aria-modal');
inerted.forEach(function(e){e.inert=false});inerted=[];
if(n)[].forEach.call(body.children,function(e){if(e!==P&&e!==scrim&&e!==toast&&!e.inert&&e.tagName!=='SCRIPT'){e.inert=true;inerted.push(e)}})}
function param(){var q=new URLSearchParams(location.search),k=q.get('item')||'';return !q.has('sent')&&KEY.test(k)?k:''}
// opening from the list adds one history entry; going on to another item replaces it, so one Back returns to the lists
function address(k){var q=location.pathname+'?item='+encodeURIComponent(k);if(param()===k)return;if(param())history.replaceState(history.state,'',q);else{history.scrollRestoration='manual';history.pushState({brief:1},'',q)}}
function say(t){toast.textContent=t;toast.removeAttribute('data-k');toast.hidden=false;clearTimeout(tt);tt=setTimeout(function(){toast.hidden=true},4000)}
// a send that failed on an item that is not on screen: stays until he opens it or dismisses it
function tell(k,why){clearTimeout(tt);var li=rowFor(k),id=li&&$('.ir-id',li);toast.textContent='';toast.setAttribute('data-k',k);
toast.appendChild(el('span','',SST('js.brief.toast',{item:id?id.textContent:k,why:why})));
toast.appendChild(btn('b main',SST('js.brief.open_item'),function(){toast.hidden=true;open(k,cur?'step':'click')}));
toast.appendChild(btn('b',SST('js.brief.dismiss'),function(){toast.hidden=true}));toast.hidden=false}
function fill(me){V.innerHTML='';var w=el('p','bload',SST('js.brief.loading'));w.id='brief-title';V.appendChild(w);P.focus({preventScroll:true});
var n=++me.n;load(page(me.k)+'/brief').then(function(a){if(cur===me&&me.n===n)render(a)},function(){if(cur===me&&me.n===n)failed(me)})}
function failed(me){V.innerHTML='';var w=el('div','bfail'),h=el('p','',SST('js.brief.fail_load'));h.id='brief-title';h.setAttribute('role','alert');w.appendChild(h);
w.appendChild(btn('b main bretry',SST('js.brief.retry'),function(){if(cur===me)fill(me)}));w.appendChild(link(me.k,'b',SST('js.brief.open_page')));V.appendChild(w)}
function open(k,how){var me=cur={k:k,fp:'',sent:null,sentFp:'',seen:0,n:0};
if(P.hidden){homeY=window.scrollY;last=document.activeElement;P.hidden=false;body.classList.add('brief-open')}
lay();mark();$('[data-bact=full]',P).setAttribute('href',page(k)+'/brief');
if(toast.getAttribute('data-k')===k)toast.hidden=true;
if(how==='click'||how==='step')address(k);
if(how==='click'&&!MQ.matches){var li=rowFor(k);if(li)li.scrollIntoView({block:'nearest'})}
fill(me)}
function closeUI(){if(!cur)return;var k=cur.k;cur=null;P.hidden=true;P.style.transform='';V.innerHTML='';document.dispatchEvent(new Event('stackshot:redrawn'));body.classList.remove('brief-open');lay();mark();
if(MQ.matches)window.scrollTo(0,homeY);var li=rowFor(k),a=li&&$('a.ir-link',li),t=a&&a.getClientRects().length?a:last;if(t&&t.focus)t.focus({preventScroll:true})}
function close(){if(!cur)return;var p=param();closeUI();if(!p)return;if(history.state&&history.state.brief)history.back();else history.replaceState(null,'',location.pathname)}
function step(d){if(!cur)return;var l=rows().map(keyOf),n=l.length,i=l.indexOf(cur.k);if(!n)return;var k=i<0?l[d>0?0:n-1]:l[(i+d+n)%n];if(k!==cur.k)open(k,'step')}
// the next of his turn not answered here, the ones in a folded part of the list included
function nextOpen(){var l=all('#your-move li.irow.hrow').map(keyOf).filter(Boolean),i=l.indexOf(cur.k),k=l.slice(i+1).concat(l.slice(0,i+1)).filter(function(x){return x!==cur.k&&!ANSWERED[x]})[0];
if(k)open(k,'step');else{close();say(SST('js.brief.all_done'))}}
// the rows the page has now: each gets its draft once, and says what is held for it (while the item is open, its draft is the panel's to set aside, not a new row's)
function restore(){all('li.irow.hrow').forEach(function(li){var k=keyOf(li),r=rowForm(li);if(!k)return;if(r&&!r._ss){r._ss=1;if(D[k]&&!li.classList.contains('sent'))put(k,r,!(cur&&cur.k===k&&boxForm()))}rowNote(k)})}
document.addEventListener('stackshot:newer',function(e){if(cur&&cur.seen!==e.detail){cur.seen=e.detail;check()}});
document.addEventListener('stackshot:swapped',function(){pills();Object.keys(ANSWERED).forEach(function(k){var li=rowFor(k);if(li&&rowForm(li)&&!li.classList.contains('sent'))delete ANSWERED[k]});      // a row that asks again is open again
restore();lockAll();mark();check()});
// a row's own Send: one at a time per item, and the item's other forms are shut with it
document.addEventListener('submit',function(e){var f=e.target;if(!f||!f.matches||!f.matches('form.hanswer')||e.defaultPrevented)return;var k=keyOf(f.closest('li.irow.hrow')),tk=$('input[name=token]',f);if(!k||!tk||!tk.value)return;
if(SENDING[k]){e.preventDefault();return}
var p=chosen(f),d=entry(k);if(d.f&&d.f!==family(f))stash(d);d.t=noteOf(f);d.c=p?p.value:'';d.l=p?label(p):'';d.r=refOf(f);d.f=d.c||d.t?family(f):'';d.s=1;delete d.e;
var s=SENDING[k]={v:e.submitter?e.submitter.value:'',row:true};save();
setTimeout(lockAll,0);      // after the form's data is taken: a button shut now would not be sent
setTimeout(function(){if(SENDING[k]!==s)return;delete SENDING[k];lockAll();failure(k,SST('js.brief.unsure'))},LIMIT)},true);
document.addEventListener('click',function(e){if(e.defaultPrevented||e.button!==0)return;var t=e.target,li=t.closest&&t.closest('li.irow.hrow');if(!li)return;
if(!t.closest('.bopen')){if(e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;
if(!t.closest('a.ir-link')){var x=t.closest('a,button,summary,input,textarea,select,label,form,details,.draft,.sentline,.isent,.rsz,[data-tip],[title]:not([title=""])');if((x&&li.contains(x))||String(window.getSelection()))return}}
var k=keyOf(li);if(!k)return;e.preventDefault();open(k,cur?'step':'click')});
P.addEventListener('click',function(e){var b=e.target.closest('[data-bact]');if(b){var a=b.getAttribute('data-bact');if(a==='prev')step(-1);else if(a==='next')step(1);else if(a==='close')close();return}
if(e.target.closest('.bnext'))nextOpen()});
scrim.addEventListener('click',close);
document.addEventListener('keydown',function(e){if(!cur||e.defaultPrevented||e.isComposing||e.keyCode===229)return;var t=e.target,
typing=!!t&&(/^(TEXTAREA|SELECT)$/.test(t.tagName)||(t.tagName==='INPUT'&&!/^(radio|checkbox|button|submit)$/.test(t.type))||t.isContentEditable);
if(e.key==='Escape'){if(typing&&!P.contains(t))return;e.preventDefault();if(typing){t.blur();P.focus({preventScroll:true})}else close();return}
if((e.key==='j'||e.key==='k')&&!typing&&!e.ctrlKey&&!e.metaKey&&!e.altKey){e.preventDefault();step(e.key==='j'?1:-1)}});
// the sheet is dragged down by its head to close it
P.addEventListener('pointerdown',function(e){if(!MQ.matches||e.button!==0||!e.target.closest('.brief-top,.bhead')||e.target.closest('a,button'))return;drag={id:e.pointerId,y:e.clientY,d:0};try{P.setPointerCapture(e.pointerId)}catch(x){}});
P.addEventListener('pointermove',function(e){if(drag&&e.pointerId===drag.id){drag.d=Math.max(0,e.clientY-drag.y);P.style.transform='translateY('+drag.d+'px)'}});
function drop(e){if(!drag||e.pointerId!==drag.id)return;var d=drag.d;drag=null;P.style.transform='';if(e.type==='pointerup'&&d>90)close()}
P.addEventListener('pointerup',drop);P.addEventListener('pointercancel',drop);
if(MQ.addEventListener)MQ.addEventListener('change',lay);
window.addEventListener('popstate',function(){history.scrollRestoration='auto';var k=param();if(k){if(!cur||cur.k!==k)open(k,'pop')}else closeUI()});
// this page brought back by the browser (Back from another one): the drafts may have been sent or changed since it was left
window.addEventListener('pageshow',function(e){if(!e.persisted)return;var was=D;if(stored)D=read()||D;
Object.keys(SENDING).forEach(function(k){if(SENDING[k].row)delete SENDING[k]});lost();
all('li.irow.hrow').forEach(function(li){var k=keyOf(li),r=rowForm(li);if(!k)return;if(r&&!li.classList.contains('sent')&&(was[k]||D[k]))put(k,r,false);rowNote(k)});lockAll();if(cur&&!SENDING[cur.k])latest()});
// the live refresh reloads the whole page when its frame changed: not while a send is under way, or while an answer is half-written in a box that is still there
// (a draft of an item that has left the lists is kept in the browser and holds nothing up). takes: a title's link opens the panel, in the installed app too.
window.ssBrief={draft:function(){if(Object.keys(SENDING).length)return true;return Object.keys(D).some(function(k){var d=D[k];if(!(d.c||d.t||(!stored&&d.h)))return false;if(!stored)return true;
var li=rowFor(k);return !!(cur&&cur.k===k&&boxForm())||!!(li&&rowForm(li)&&!li.classList.contains('sent'))})},
takes:function(a){return !!a&&a.classList.contains('ir-link')&&!!keyOf(a.closest('li.irow.hrow'))}};
pills();restore();var k0=param();if(k0)open(k0,'load')})();""".replace("__NARROW__", _NARROW).replace("@ROOT@", PREFIX)
