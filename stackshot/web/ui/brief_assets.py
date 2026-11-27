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
            '<div class="brief-top"><span class="bgrab" aria-hidden="true"></span><div class="brief-bar"><span class="bwho"></span>'
            + btn("prev", "brief.prev", "&#8249;", " (k)") + btn("next", "brief.next", "&#8250;", " (j)")
            + f'<a class="b" data-bact="full">{_html.escape(_t("brief.full"))}</a><a class="b" data-bact="detail">{_html.escape(_t("brief.detail"))}</a>'
            + btn("close", "brief.close", "&#215;", " (Esc)")
            + '</div></div><div id="brief-main"></div></aside><p id="brief-toast" role="status" hidden></p>')


CSS = """
:root{--bw:min(560px,48vw)}
/* the row's button is a chip of its own, not a `.b` button: small to look at, a full target for a finger */
.bopen{float:right;position:relative;margin:0 0 0 8px;padding:1px 10px;font:inherit;font-size:13px;line-height:20px;white-space:nowrap;border:1px solid var(--line);border-radius:999px;background:none;color:var(--mut);cursor:pointer}
.bopen:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
@media(hover:hover){.bopen:hover{border-color:var(--acc);color:var(--fg)}}
@media(pointer:coarse){.bopen::after{content:'';position:absolute;left:0;right:0;top:50%;height:44px;transform:translateY(-50%)}}
li.irow.hrow.is-open{background:var(--selbg);box-shadow:0 0 0 2px var(--acc)}
li.irow.hrow.sent>.ir-top,li.irow.hrow.sent>.ir-det{opacity:.45}
#brief{position:fixed;z-index:30;top:0;right:0;bottom:0;width:var(--bw);display:flex;flex-direction:column;background:var(--bg);border-left:1px solid var(--line);box-shadow:-10px 0 24px -18px rgba(0,0,0,.45);outline:0}
#brief[hidden],#brief-scrim[hidden],#brief-toast[hidden]{display:none}
.brief-top{flex:none;background:var(--card)}
.bgrab{display:none}
.brief-bar{display:flex;align-items:center;gap:6px;padding:10px 16px 0}
.brief-bar .bwho{flex:1 1 auto;min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;font-size:13px;color:var(--mut)}
.brief-bar .b{flex:none;min-height:32px;padding:3px 9px}
@media(pointer:coarse){.brief-bar .b{min-width:44px;min-height:44px}}
#brief-main{flex:1 1 auto;min-height:0;display:flex;flex-direction:column}
.bload{margin:0;padding:20px 16px;color:var(--mut)}
.bchanged{flex:none;display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:8px 16px;border-bottom:1px solid var(--warn);background:var(--card);font-size:13px}
.bitem{flex:1 1 auto;min-height:0;display:flex;flex-direction:column}
.bhead{flex:none;padding:4px 16px 10px;border-bottom:1px solid var(--line);background:var(--card)}
#brief .bhead>.bwho{display:none}
.bhead>.bwho{margin:6px 0 0;font-size:13px;color:var(--mut)}
.bitem .btitle{margin:6px 0 2px;font-size:16px;line-height:22px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow-wrap:anywhere}
.btitle .ir-id{color:var(--mut)}
.bstate{margin:4px 0 0;font-size:13px;color:var(--mut)}
.bbody{flex:1 1 auto;min-height:0;display:flex;flex-direction:column;overflow-y:auto;overscroll-behavior:contain;padding:12px 16px 0;overflow-wrap:anywhere}
.bbody>*{flex:none;min-width:0}
.bbody::after{content:'';order:1;flex:none;height:20px}
.bsec{margin:0 0 14px}
.bsec>h3{margin:0 0 6px;font-size:13px;font-weight:700;color:var(--mut)}
.bsec .desc{margin:0;opacity:1;font-size:14px}
.bmore>summary{cursor:pointer;color:var(--mut);font-size:13px;padding:4px 0}
.bpast{margin:0;padding-left:20px;font-size:14px;line-height:1.5}
.bsent .bnext{margin:0 0 12px}
.bbody>form.ianswer[data-cards]{display:contents}
.bbody>form.ianswer[data-cards]>.acards{margin-bottom:14px}
.bbody .bfoot,.bbody>form.ianswer:not([data-cards]){order:2;position:sticky;bottom:0;z-index:2;margin:auto -16px 0;padding:8px 16px calc(10px + env(safe-area-inset-bottom));border:0;border-top:2px solid var(--line);border-radius:0;background:var(--card)}
.bitem .bfoot label,.bbody>form.ianswer:not([data-cards])>label{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.bitem form.ianswer textarea{height:38px;min-height:38px}
.bitem form.ianswer textarea:focus,.bitem form.ianswer textarea:not(:placeholder-shown){height:84px}
@media(pointer:coarse){.bitem .abox textarea:placeholder-shown:not(:focus){height:38px!important}.bitem form.ianswer .abox textarea:focus{min-height:84px}}
.bpicked{margin:0 0 6px;font-size:13px;color:var(--mut)}
.bitem .abtns,.bitem .abtns-send{align-items:center}
.bitem .ahint{display:none}
.bitem.justsent form[data-comment-only]{display:none}
#brief-toast{position:fixed;left:50%;bottom:24px;z-index:32;transform:translateX(-50%);margin:0;padding:10px 16px;border:1px solid var(--ibd);border-radius:8px;background:var(--card);color:var(--fg);font-size:14px;box-shadow:0 6px 24px rgba(0,0,0,.22)}
#brief-scrim{position:fixed;inset:0;z-index:29;background:rgba(0,0,0,.42)}
body.brief-open::after{display:none}
@media(min-width:800px){body.brief-open #layout,body.panel-pin.brief-open #layout{padding-right:var(--bw)}
body.brief-open #panel,body.brief-open #panel-edge,body.brief-open #panel-scrim,body.brief-open #panel-open,body.brief-open header.top .theme,body.brief-open .fab,body.brief-open #totop{visibility:hidden}
#brief-scrim{display:none}}
@media__NARROW__{body.brief-open #panel-open,body.brief-open header.top .theme{visibility:hidden}
#brief{top:auto;left:0;width:auto;height:92vh;height:92dvh;border-left:0;border-radius:16px 16px 0 0;overflow:hidden}
.brief-top,#brief .bhead{touch-action:none}
.bgrab{display:block;width:44px;height:5px;margin:0 auto;border-radius:3px;background:var(--ibd);position:relative;top:6px}
.brief-bar{justify-content:flex-end;padding:12px 12px 0}
.brief-bar .bwho{visibility:hidden}
.brief-bar .b{min-width:44px;min-height:44px}
.bitem .btitle{font-size:15px}
.bitem form.ianswer textarea{font-size:16px}
.bitem .bfoot{display:grid;grid-template-columns:minmax(0,1fr) auto;column-gap:8px;align-items:center}
.bitem .bfoot>*{grid-column:1/-1}
.bitem .bfoot>.abox{grid-column:1}
.bitem .bfoot>.abtns-send{grid-column:2;flex-wrap:nowrap;margin:0}
html.sheet,html.sheet body{overflow:hidden}}
main.briefpage{overflow-wrap:anywhere}
.bpbar{display:flex;gap:8px;margin:12px 0}
#brief-page>.bitem{max-width:760px;border:1px solid var(--line);border-radius:12px}
#brief-page .bhead{border-radius:12px 12px 0 0}
#brief-page .bbody{flex:none;overflow:visible}
#brief-page .bfoot,#brief-page .bbody>form.ianswer:not([data-cards]){border-radius:0 0 12px 12px}
body:has(main.briefpage) .fab,body:has(main.briefpage) #totop{display:none}
.bbody .iwait{margin:0 0 14px}.bbody .iwait h2{margin:0 0 6px;font-size:13px;font-weight:700;color:var(--mut)}
.bbody .iask,.bbody .draft{margin-bottom:14px}.bbody .isent{margin-bottom:12px}
""".replace("__NARROW__", _NARROW)

# One script for both places. On the home page it opens the brief of a clicked row in the panel (the address becomes ?item=<key>: Back, Escape and the close button
# close it), keeps a half-written answer while the lists refresh and per item while the panel is open on another, and says when the open item changed under it.
# In both places an answer is the page's own form, posted to the one answer route with `Accept: application/json`; the brief read again with ?sent=<code> says what happened.
# A brief that cannot be read sends the browser to the item's own page.
JS = r"""(function(){
if(!window.fetch||!window.DOMParser||!window.URLSearchParams)return;
var P=document.getElementById('brief'),FULL=document.getElementById('brief-page');
if(!P&&!FULL)return;
var KEY=/^([a-z][0-9]+|[1-9][0-9]*|board-tmp-[a-z0-9-]*[a-z0-9]-[1-9][0-9]*)$/,CARRY='ss-brief-draft:',busy=false;
function $(s,r){return (r||document).querySelector(s)}
function all(s,r){return [].slice.call((r||document).querySelectorAll(s))}
function page(k){return '@ROOT@/items/'+k}
function load(url){var c=window.AbortController?new AbortController():null,t=c?setTimeout(function(){c.abort()},15000):0;
return fetch(url,{cache:'no-store',credentials:'same-origin',headers:{'Accept':'text/html'},signal:c?c.signal:undefined})
.then(function(r){if(!r.ok)throw 0;return r.text()}).then(function(x){clearTimeout(t);var a=new DOMParser().parseFromString(x,'text/html').querySelector('article.bitem');if(!a)throw 0;return a},function(e){clearTimeout(t);throw e})}
function form(r){return r?$('form.ianswer',r):null}
function drawn(f){return !!f&&f.matches('[data-cards],[data-step]')}
function val(f){var p=$('input[name=choice]:checked',f),t=$('textarea',f),x=$('input[name=ref]',f);return{c:p?p.value:'',t:t?t.value:'',r:x?x.value:''}}
function picked(f){var o=$('.bpicked',f);if(!o)return;var p=$('input[name=choice]:checked',f),w=SST('js.brief.none');
if(p){var l=$('.alab',p.closest('.acard')),k=l&&$('.akey',l);if(l)w=k?k.textContent+' · '+l.textContent.slice(k.textContent.length):l.textContent}
o.textContent=SST('js.brief.picked',{what:w})}
// a pick belongs to the question it was made on (the form's ref): on a question written again only the note comes back
function put(f,d){var t=$('textarea',f),x=$('input[name=ref]',f),same=!x||!d.r||x.value===d.r;if(t&&t.value!==d.t)t.value=d.t;
all('input[name=choice]',f).forEach(function(i){i.checked=same&&i.value===d.c});var p=$('input[name=choice]:checked',f);f._was=p?p.value:'';picked(f);if(window.ssCards&&drawn(f))ssCards.sync(f)}
function send(f,btn,done){if(busy)return;var d=new FormData(f);if(btn&&btn.name)d.append(btn.name,btn.value);
var E=$('.aerr',f),bs=all('button',f).filter(function(b){return !b.classList.contains('xp-b')}),L=btn?btn.innerHTML:'';
busy=true;f.setAttribute('aria-busy','true');bs.forEach(function(b){b.disabled=true});if(btn){btn.setAttribute('aria-busy','true');btn.textContent=SST('js.answer.sending')}if(E)E.hidden=true;
function back(msg){busy=false;f.removeAttribute('aria-busy');bs.forEach(function(b){b.disabled=false});if(btn){btn.removeAttribute('aria-busy');btn.innerHTML=L}if(E){E.textContent=msg;E.hidden=false}if(window.ssCards&&drawn(f))ssCards.sync(f)}
function fail(why){back(SST('js.answer.nothing_sent',{why:why}))}
fetch(f.getAttribute('action'),{method:'POST',body:new URLSearchParams(d),credentials:'same-origin',cache:'no-store',headers:{'Accept':'application/json'}})
.then(function(r){return r.text().then(function(x){var j=null;try{j=JSON.parse(x)}catch(e){}
if(r.ok&&j&&typeof j.sent==='string'&&j.sent)return done(j.sent,back);
x=String(x||'').replace(/\s+/g,' ').trim();fail(!r.ok&&x&&x.length<400&&x.charAt(0)!=='<'?x:SST('js.answer.bad_reply',{what:r.ok?SST('js.answer.unexpected_page'):r.status}))})})
.catch(function(){fail(SST('js.answer.no_answer'))})}
// after the board took the post: a code that wrote nothing leaves the form as it is with the notice under it (the article's data-keep lists them), any other goes on to `then`
function after(k,art,code,back,then){var q='?sent='+encodeURIComponent(code),keep=(art.getAttribute('data-keep')||'').split(' ').indexOf(code)>=0;
load(page(k)+'/brief'+q).then(function(a){var n=$('.bsent',a);if(keep)return back(n?n.textContent:SST('js.answer.nothing_sent',{why:code}));busy=false;then(a,n)},
function(){if(keep)back(SST('js.answer.nothing_sent',{why:code}));else location.assign(page(k)+q)})}
function onSend(root,run){root.addEventListener('submit',function(e){var f=e.target;if(!f.matches('form.ianswer')||e.submitter===undefined)return;e.preventDefault();run(f,e.submitter)})}
function onType(fn){['input','change','click'].forEach(function(n){document.addEventListener(n,function(e){var t=e.target;if(t&&t.matches&&t.matches('input[name=choice],textarea[name=text]')&&t.form)fn(t.form)})})}
function carry(k,d){try{if(d===undefined){var v=sessionStorage.getItem(CARRY+k);sessionStorage.removeItem(CARRY+k);return v?JSON.parse(v):null}sessionStorage.setItem(CARRY+k,JSON.stringify(d))}catch(e){return null}}
if(FULL){var art=$('article.bitem',FULL),first=form(art),key=art?art.getAttribute('data-key'):'';
if(first){var kept=carry(key);if(kept&&!/[?&]sent=/.test(location.search))put(first,kept);else picked(first)}
onType(picked);
onSend(FULL,function(f,b){send(f,b,function(code,back){after(key,art,code,back,function(){location.replace(page(key)+'/brief?sent='+encodeURIComponent(code))})})});
return}
var scrim=$('#brief-scrim'),main=$('#brief-main'),toast=$('#brief-toast'),root=document.documentElement,body=document.body,MQ=matchMedia('__NARROW__'),
cur=null,D={},ANSWERED={},homeY=0,last=null,inerted=[],drag=null,tt=0;
function keyOf(li){var a=li&&$('a.ir-link',li),m=a&&/\/items\/([^\/?#]+)$/.exec(a.getAttribute('href')||'');return m&&KEY.test(m[1])?m[1]:''}
function rows(sel){return all(sel||'li.irow.hrow').filter(function(li){return li.getClientRects().length&&keyOf(li)})}
function rowFor(k){return all('li.irow.hrow').filter(function(li){return keyOf(li)===k})[0]||null}
function rowForm(li){return li?$('form.hanswer',li):null}
function pills(){all('li.irow.hrow').forEach(function(li){if($('.bopen',li)||!keyOf(li))return;var p=$('.ir-proj',li);if(!p){p=document.createElement('div');p.className='ir-proj';li.insertBefore(p,li.firstChild)}
var b=document.createElement('button');b.type='button';b.className='bopen';b.textContent=SST('js.brief.open');p.appendChild(b)})}
function mark(){all('li.irow.is-open').forEach(function(li){li.classList.remove('is-open')});var li=cur&&rowFor(cur.k);if(li)li.classList.add('is-open')}
// the sheet is modal: the rest of the page is inert under it. The panel on a wide screen is not, the lists stay in use beside it
function lay(){var on=!!cur,n=on&&MQ.matches;root.classList.toggle('sheet',n);scrim.hidden=!n;if(n)P.setAttribute('aria-modal','true');else P.removeAttribute('aria-modal');
inerted.forEach(function(e){e.inert=false});inerted=[];
if(n)[].forEach.call(body.children,function(e){if(e!==P&&e!==scrim&&e!==toast&&!e.inert&&e.tagName!=='SCRIPT'){e.inert=true;inerted.push(e)}})}
function param(){var q=new URLSearchParams(location.search),k=q.get('item')||'';return !q.has('sent')&&KEY.test(k)?k:''}
// opening from the list adds one history entry; going on to another item replaces it, so one Back returns to the lists
function address(k){var q=location.pathname+'?item='+encodeURIComponent(k);if(param()===k)return;if(param())history.replaceState(history.state,'',q);else{history.scrollRestoration='manual';history.pushState({brief:1},'',q)}}
function keepDraft(){var f=cur&&form(main);if(!f)return;var d=val(f);if(d.c||d.t)D[cur.k]=d;else delete D[cur.k]}
function draftFor(k){var f=rowForm(rowFor(k)),d=f&&val(f);return d&&(d.c||d.t)?d:D[k]||null}
function say(t){toast.textContent=t;toast.hidden=false;clearTimeout(tt);tt=setTimeout(function(){toast.hidden=true},4000)}
function render(a,keep){var b=$('.bbody',main),y=keep&&b?b.scrollTop:0,had=P.contains(document.activeElement),n=document.importNode(a,true);
main.innerHTML='';main.appendChild(n);cur.fp=n.getAttribute('data-fp')||'';
var who=$('.bhead>.bwho',n);$('.brief-bar .bwho',P).textContent=who?who.textContent:'';
var f=form(n);if(f){var d=draftFor(cur.k);if(d)put(f,d);else{picked(f);if(window.ssCards&&drawn(f))ssCards.sync(f)}}
if(cur.sent){n.classList.add('justsent');var s=$('.bsent',n),into=$('.bbody',n);if(!s){s=cur.sent.cloneNode(true);into.insertBefore(s,into.firstChild)}
var x=document.createElement('button');x.type='button';x.className='b bnext';x.textContent=SST('js.brief.next');s.appendChild(x)}
$('.bbody',n).scrollTop=y;if(had&&!P.contains(document.activeElement))P.focus({preventScroll:true});
document.dispatchEvent(new Event('stackshot:inserted'))}
function open(k,how){keepDraft();var me=cur={k:k,fp:'',sent:null,seen:0};
if(P.hidden){homeY=window.scrollY;last=document.activeElement;P.hidden=false;body.classList.add('brief-open')}
lay();mark();$('[data-bact=full]',P).setAttribute('href',page(k)+'/brief');$('[data-bact=detail]',P).setAttribute('href',page(k));
main.innerHTML='';$('.brief-bar .bwho',P).textContent='';var w=document.createElement('p');w.className='bload';w.id='brief-title';w.textContent=SST('js.brief.loading');main.appendChild(w);P.focus({preventScroll:true});
if(how==='click'&&!MQ.matches){var li=rowFor(k);if(li)li.scrollIntoView({block:'nearest'})}
load(page(k)+'/brief').then(function(a){if(cur!==me)return;render(a);if(how==='click'||how==='step')address(k)},
function(){if(cur!==me)return;closeUI();if(how==='load'||how==='pop')location.replace(page(k));else location.assign(page(k))})}
function closeUI(){if(!cur)return;keepDraft();var k=cur.k;cur=null;P.hidden=true;P.style.transform='';main.innerHTML='';body.classList.remove('brief-open');lay();mark();
if(MQ.matches)window.scrollTo(0,homeY);var li=rowFor(k),t=(li&&$('a.ir-link',li))||last;if(t&&t.focus)t.focus({preventScroll:true})}
function close(){if(!cur)return;var p=param();closeUI();if(!p)return;if(history.state&&history.state.brief)history.back();else history.replaceState(null,'',location.pathname)}
function step(d){if(!cur)return;var l=rows().map(keyOf),n=l.length,i=l.indexOf(cur.k);if(!n)return;var k=i<0?l[d>0?0:n-1]:l[(i+d+n)%n];if(k!==cur.k)open(k,'step')}
function nextOpen(){var l=rows('#your-move li.irow.hrow').map(keyOf),i=l.indexOf(cur.k),k=l.slice(i+1).concat(l.slice(0,i+1)).filter(function(x){return x!==cur.k&&!ANSWERED[x]})[0];
if(k)open(k,'step');else{close();say(SST('js.brief.all_done'))}}
function rowSent(k,words){var li=rowFor(k);if(!li)return;li.classList.add('sent');var f=rowForm(li);if(f){f.reset();f.hidden=true;f.removeAttribute('data-gid')}
if(!$('.bsentline',li)){var p=document.createElement('p');p.className='isent ok bsentline';p.textContent=words;li.appendChild(p)}}
onSend(main,function(f,b){var me=cur,a=$('article.bitem',main);send(f,b,function(code,back){after(me.k,a,code,back,function(n,s){
var ok=!!s&&s.getAttribute('data-ok')==='1',words=s?s.textContent:'';delete D[me.k];
if(ok){ANSWERED[me.k]=1;rowSent(me.k,words)}else{var r=rowForm(rowFor(me.k));if(r)r.reset()}
if(cur===me){me.sent=ok?s.cloneNode(true):null;render(n);P.focus({preventScroll:true})}
if(!ok)window.dispatchEvent(new Event('focus'))})})});      // refused: the row is behind, so ask for the lists now; a sent one stays dimmed until their next refresh
// the lists moved on: read the open item again; with nothing half-written it is drawn anew, else a line says it changed and the draft stays
function latest(){var me=cur;load(page(me.k)+'/brief').then(function(a){if(cur!==me)return;keepDraft();render(a,true)},function(){})}
function check(){var me=cur;if(!me||!me.fp||busy)return;load(page(me.k)+'/brief').then(function(a){if(cur!==me||busy)return;var old=$('.bchanged',main);
if(a.getAttribute('data-fp')===me.fp){if(old)old.remove();return}
keepDraft();var f=form(main),at=document.activeElement,typing=!!f&&f.contains(at)&&at.tagName==='TEXTAREA';
if(!D[me.k]&&!typing){render(a,true);return}
if(old)return;var n=document.createElement('div');n.className='bchanged';n.setAttribute('role','status');var s=document.createElement('span');s.textContent=SST('js.brief.changed');
var x=document.createElement('button');x.type='button';x.className='b warn';x.textContent=SST('js.brief.show_latest');x.addEventListener('click',latest);n.appendChild(s);n.appendChild(x);main.insertBefore(n,main.firstChild)},function(){})}
document.addEventListener('stackshot:newer',function(e){if(cur&&cur.seen!==e.detail){cur.seen=e.detail;check()}});
document.addEventListener('stackshot:swapped',function(){pills();mark();check()});
// the row and the panel are one draft: what is picked or written in either shows in the other
onType(function(f){if(!cur)return;if(main.contains(f)){picked(f);keepDraft();var r=rowForm(rowFor(cur.k));if(r)put(r,val(f))}
else if(f.matches('form.hanswer')&&keyOf(f.closest('li.irow'))===cur.k){var p=form(main);if(p){put(p,val(f));keepDraft()}}});
document.addEventListener('click',function(e){if(e.defaultPrevented||e.button!==0)return;var t=e.target,li=t.closest&&t.closest('li.irow.hrow');if(!li)return;
if(!t.closest('.bopen')){if(e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;
if(!t.closest('a.ir-link')){var x=t.closest('a,button,summary,input,textarea,select,label,form,details,.draft,.sentline,.isent,.rsz');if((x&&li.contains(x))||String(window.getSelection()))return}}
var k=keyOf(li);if(!k)return;e.preventDefault();open(k,cur?'step':'click')});
P.addEventListener('click',function(e){var b=e.target.closest('[data-bact]');if(b){var a=b.getAttribute('data-bact');if(a==='prev')step(-1);else if(a==='next')step(1);else if(a==='close')close();
else if(a==='full'&&cur){keepDraft();if(D[cur.k])carry(cur.k,D[cur.k])}return}
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
// the live refresh reloads the whole page when its frame changed: not while an answer is half-written here
window.ssBrief={draft:function(){keepDraft();return Object.keys(D).length>0}};
pills();var k0=param();if(k0)open(k0,'load')})();""".replace("__NARROW__", _NARROW).replace("@ROOT@", PREFIX)
