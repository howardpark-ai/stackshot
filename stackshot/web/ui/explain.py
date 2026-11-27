"""ui/explain.py — the one "?" control that holds a page's explainer text, and the popup a tap opens on words that carry their explanation in an attribute.

Text that explains what a section is, or how something works, is not drawn on the page: it sits behind a small "?" next to the thing it explains (CONTRIBUTING.md, *Page
text*). `explain(key, text, what)` is the markup; CSS joins the shared stylesheet (render.Board._css) and SCRIPT ends every page's body (render._FAB_PAIR), so a page
that draws the board's chrome only has to call explain().

The popup opens on a tap or click, and on a desktop also on hover and on keyboard focus; Escape, a tap outside and tabbing away close it. The button's accessible
description is the text itself, so a screen reader says it on focus, open or not. The popup stays inside the window and inside any ancestor that clips it. An Escape that
closes it reaches no listener added after this script, so SCRIPT comes ahead of the scripts of a panel a "?" can sit in. The script is delegated on the document and
remembers the open popup by its key, so a block the home page's live refresh swaps in keeps it open.

A hover explanation (a `data-tip` or a `title`) on anything that is not a control opens the same way for a finger: a tap or click on it draws its text in a popup of
the same look, so a page writes the attribute and nothing else. A control (a link, a button, a form field, a <summary>) and whatever is inside one keep their own tap.
`data-xt-also` on an element adds its title under the text of an explanation inside it. A second tap, a tap elsewhere and Escape close the popup, and only one popup
is open at a time. A script that redraws elements with an explanation (the side panel's Audit card) says so with a `stackshot:redrawn` event."""
from __future__ import annotations

import html as _html

from stackshot.web import i18n as _i18n


def explain(key: str, text: str, what: str, lang: str | None = None) -> str:
    """HTML: the "?" button and its popup. `key` names this explainer on the page (letters, digits and hyphens, one per page, the same on every draw, so an open popup
    survives a redraw); `text` is the explainer and `what` the name of the thing it explains, both plain text in the request's language (escaped here). Every element
    is phrasing content, so it may sit in a paragraph; put it beside a heading or a <summary>, not inside one, so it does not join the heading's name."""
    k = _html.escape(key, quote=True)
    label = _html.escape(_i18n.t("explain.about", lang, what=what), quote=True)
    return (f'<span class="xp" data-xp="{k}"><button type="button" class="xp-b" id="xpb-{k}" aria-label="{label}" aria-expanded="false" aria-controls="xp-{k}" aria-describedby="xp-{k}">'
            f'<span aria-hidden="true">?</span></button><span class="xp-pop" id="xp-{k}" role="tooltip" tabindex="-1" hidden>{_html.escape(text, quote=True)}</span></span>')


def head(heading: str, tip: str) -> str:
    """HTML: a heading with its "?" beside it on one line. `heading` is the whole <h1> or <h2> element, `tip` what explain() gave; both are markup. The wrapper takes over
    the heading's margins and rule (class xp-h1 or xp-h2), so the rule still runs under the whole line."""
    return f'<div class="xp-head xp-{heading[1:3]}">{heading}{tip}</div>'


# `word-break:keep-all` keeps a word of a language written with spaces between words whole (Korean breaks inside a word without it); a word wider than the popup
# still breaks (`overflow-wrap:anywhere`).
# The popup a tap opens on an explanation in an attribute (.xt-pop) is fixed to the screen at the end of <body>, so no panel or table clips it. On a screen with a
# finger the words say they take a tap (iOS sends a click only to an element with a pointer cursor), the CSS tooltip of a hover is off where there is no hover, and
# the two marks too small for a finger (the stale sign in a list, the box of a waiting line) get a larger target.
# The button is a 28 px target (44 px for a finger) round an 18 px circle, and it takes its own room: a line that holds one grows, so the target never lies over the words or
# a link on the line above or below. Only a heading's line, which has blank margins round it, lets a finger's target reach 4 px into them. A waiting item's rows align on
# their words, so a label stays level with a line that grew. The popup sets every inherited text property itself, since it can sit in a heading.
CSS = """
.xp-head{display:flex;flex-wrap:wrap;align-items:center;gap:8px 4px}.xp-head.xp-h1>h1,.xp-head.xp-h2>h2{margin:0;border:0;padding:0}
.xp-head.xp-h1{margin:0 0 16px}.xp-head.xp-h2{margin:32px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line)}
main.audits-page .xp-head.xp-h2{margin:22px 0 8px}.lnew>.xp-head.xp-h2,.lcompleted>.xp-head.xp-h2{margin:28px 0 4px}
.xp{position:relative;display:inline-block;vertical-align:middle;line-height:1}
dl.iwl{align-items:baseline}
.xp-b{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;margin:0;padding:0;border:0;border-radius:8px;background:none;color:var(--mut);font-family:inherit;cursor:pointer}
.xp-b>span{display:inline-flex;align-items:center;justify-content:center;box-sizing:border-box;width:18px;height:18px;border:1.5px solid currentColor;border-radius:50%;font-size:12px;font-weight:600;line-height:1}
.xp-b:hover,.xp-b[aria-expanded=true]{color:var(--fg)}.xp-b:focus-visible{outline:2px solid var(--acc);outline-offset:-2px;color:var(--fg)}
.xp-pop{position:absolute;top:100%;left:0;z-index:35;display:block;box-sizing:border-box;width:max-content;max-width:320px;padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);box-shadow:0 4px 16px rgba(0,0,0,.16);font-size:12px;font-style:normal;font-weight:400;line-height:1.5;letter-spacing:normal;text-transform:none;text-align:left;white-space:normal;word-break:keep-all;overflow-wrap:anywhere;cursor:auto}
.xp-pop[hidden]{display:none}
.xp-pop.xt-pop{position:fixed;z-index:1000;max-height:calc(100vh - 16px);overflow:auto;white-space:pre-line}
.tip::after{word-break:keep-all}[data-xt-open]::after{content:none!important}@media(hover:none){.tip::after{content:none!important}}
@media(any-pointer:coarse),(hover:none){html [data-tip],html [title]:not([title=""]):not(a,button,input,select,textarea,label,summary,iframe,option){cursor:pointer!important}}
@media(pointer:coarse){.iwarn[title]:not(.stw){display:inline-block;min-width:28px;min-height:24px;text-align:center}.wbox[title]{position:relative}.wbox[title]::before{content:"";position:absolute;inset:-8px}}
@media(pointer:coarse){.xp-b{width:44px;height:44px}.xp-head>.xp{margin:-4px 0}}
"""

# O is the one open popup: {k: its key, h: how it opened ('hover', 'focus' or 'pin')}. A tap or click pins it; hover and focus open only a popup that is not open, so they
# never undo its pin. stackshotExplain is explain()'s markup for a script that adds an explainer to markup the server did not draw (ui/colortool.py).
# place() measures the popup while it is fixed to the screen: one that reaches past the right edge even for the one measuring pass widens a phone's layout viewport for
# that pass, which pulls a page scrolled near its end back up. A floating button (Back to top and the round buttons above it) is drawn over the pinned side panel, whose
# popups cannot rise above it: one that would lie under a button goes to the other side of its "?", or, when no room is there, stops left of the button.
# stackshotBack gives a "?" the focus back (after Escape, or a script that moved it) without opening it or scrolling to it.
# P is the one popup a tap opened on an explanation in an attribute: {h: the element, p: the popup, tag, c: its class, t: its words, i: which of the elements alike it
# is}, so a redrawn page keeps it open on the element drawn in its place. held() is the element a tap explains: the nearest with an explanation, unless the tap is on a
# control. A tap that ends a text selection opens nothing. A popup whose element has gone, been hidden or left the screen closes.
JS = r"""(function(){var O=null,P=null,quiet=false;
window.stackshotExplain=function(key,text,label){function el(t,a,x){var n=document.createElement(t);for(var k in a)n.setAttribute(k,a[k]);if(x!==undefined)n.textContent=x;return n}
var w=el('span',{'class':'xp','data-xp':key}),b=el('button',{type:'button','class':'xp-b',id:'xpb-'+key,'aria-label':label,'aria-expanded':'false','aria-controls':'xp-'+key,'aria-describedby':'xp-'+key});
b.appendChild(el('span',{'aria-hidden':'true'},'?'));w.appendChild(b);w.appendChild(el('span',{'class':'xp-pop',id:'xp-'+key,role:'tooltip',tabindex:'-1',hidden:''},text));return w};
function wrap(t){return t&&t.closest?t.closest('.xp'):null}
function find(k){return document.querySelector('.xp[data-xp="'+k+'"]')}
function set(w,on){w.firstElementChild.setAttribute('aria-expanded',String(on));w.lastElementChild.hidden=!on}
function over(s){return [].filter.call(document.querySelectorAll('#totop,.fab'),function(f){var c=f.getBoundingClientRect();return c.left<s.x+s.W&&s.x<c.right&&c.top<s.y+s.h&&s.y<c.bottom})}
function atop(f,s){var c=f.getBoundingClientRect();function near(v,a,z){return Math.max(a+.5,Math.min(v,z-.5))}
var t=document.elementFromPoint(near((c.left+c.right)/2,Math.max(c.left,s.x),Math.min(c.right,s.x+s.W)),near((c.top+c.bottom)/2,Math.max(c.top,s.y),Math.min(c.bottom,s.y+s.h)));return !!t&&f.contains(t)}
function place(w){var b=w.firstElementChild,p=w.lastElementChild;function aside(){p.style.position='fixed';p.style.left='0px';p.style.top='0px'}aside();
var L=0,R=document.documentElement.clientWidth,T=0,H=window.innerHeight;
for(var n=w.parentElement;n&&n!==document.body&&n!==document.documentElement;n=n.parentElement){var s=window.getComputedStyle(n),c=n.getBoundingClientRect();if(s.display==='contents')continue;
if(s.overflowX!=='visible'){L=Math.max(L,c.left);R=Math.min(R,c.right)}if(s.overflowY!=='visible'){T=Math.max(T,c.top);H=Math.min(H,c.bottom)}}
var r=b.getBoundingClientRect(),o=w.getBoundingClientRect();
function spot(R){p.style.maxWidth=Math.max(0,Math.min(320,R-L-16))+'px';var W=p.offsetWidth,h=p.offsetHeight,y=r.bottom;if(y+h>H-8&&r.top-h>=T+8)y=r.top-h;
return {x:Math.max(L+8,Math.min(r.left+r.width/2-W/2,R-8-W)),y:y,W:W,h:h}}
function put(s){p.style.position='';p.style.left=(s.x-o.left)+'px';p.style.top=(s.y-o.top)+'px'}
var at=spot(R);put(at);
var f=over(at).filter(function(f){return atop(f,at)});if(!f.length)return;
var y=at.y<r.top?r.bottom:r.top-at.h,to={x:at.x,y:y,W:at.W,h:at.h};
if(y>=T+8&&y+at.h<=H-8&&!over(to).length)put(to);else{aside();put(spot(Math.min.apply(null,f.map(function(f){return f.getBoundingClientRect().left}))))}}
function hide(){if(!O)return;var w=find(O.k);O=null;if(w)set(w,false)}
function show(w,how){var k=w.getAttribute('data-xp');shut();if(O&&O.k!==k)hide();O={k:k,h:how};set(w,true);place(w)}
function is(w){return !!O&&O.k===w.getAttribute('data-xp')}
function back(e){quiet=true;try{e.focus({preventScroll:true})}finally{quiet=false}}
window.stackshotBack=back;
function words(h){var t=h.getAttribute('data-tip');if(t===null)t=h.getAttribute('title');if(!t)return '';
var u=h.parentElement&&h.parentElement.closest('[data-xt-also]'),m=u&&u.getAttribute('title');return m?t+'\n'+m:t}
function held(t){if(!t||!t.closest||t.closest('a[href],button,input,select,textarea,label,summary,iframe,.xp'))return null;var h=t.closest('[data-tip],[title]');return h&&words(h)?h:null}
function alike(q){return [].filter.call(document.getElementsByTagName(q.tag),function(n){return (n.getAttribute('class')||'')===q.c&&words(n)===q.t})}
function shut(){if(!P)return;P.h.removeAttribute('data-xt-open');P.p.remove();P=null}
function put(){if(!P)return;var h=P.h,p=P.p,r=h.isConnected&&h.getBoundingClientRect(),D=document.documentElement,W=Math.min(D.clientWidth,D.getBoundingClientRect().width||D.clientWidth),H=window.innerHeight;
if(!r||(!r.width&&!r.height)||r.bottom<=0||r.top>=H||r.right<=0||r.left>=W||window.getComputedStyle(h).visibility==='hidden'){shut();return}
p.style.maxWidth=Math.max(0,Math.min(320,W-16))+'px';p.style.left='0px';p.style.top='0px';
var w=p.offsetWidth,t=p.offsetHeight,y=r.bottom+4;if(y+t>H-8)y=r.top-4-t>=8?r.top-4-t:Math.max(8,H-8-t);
p.style.left=Math.max(8,Math.min(r.left+r.width/2-w/2,W-8-w))+'px';p.style.top=y+'px'}
function lift(h){shut();hide();var p=document.createElement('span');p.setAttribute('class','xp-pop xt-pop');p.setAttribute('role','tooltip');p.textContent=words(h);
var q={h:h,p:p,tag:h.tagName,c:h.getAttribute('class')||'',t:words(h)};q.i=alike(q).indexOf(h);P=q;h.setAttribute('data-xt-open','');document.body.appendChild(p);put()}
function redrawn(){if(!P)return;if(!P.h.isConnected){var n=alike(P)[P.i];if(!n){shut();return}P.h=n;n.setAttribute('data-xt-open','')}
if(!words(P.h)){shut();return}P.p.textContent=words(P.h);put()}
document.addEventListener('click',function(e){var w=wrap(e.target);if(!w||!e.target.closest('.xp-b'))return;e.preventDefault();if(is(w)&&O.h==='pin')hide();else show(w,'pin')});
document.addEventListener('pointerover',function(e){var w=wrap(e.target);if(w&&e.pointerType==='mouse'&&!w.contains(e.relatedTarget)&&!is(w))show(w,'hover')});
document.addEventListener('pointerout',function(e){var w=wrap(e.target);if(w&&e.pointerType==='mouse'&&!w.contains(e.relatedTarget)&&is(w)&&O.h==='hover')hide()});
document.addEventListener('pointerup',function(e){if(O&&wrap(e.target)!==find(O.k))hide();if(P&&!P.p.contains(e.target)&&!P.h.contains(e.target))shut()},true);
document.addEventListener('click',function(e){if(P&&P.p.contains(e.target))return;var h=held(e.target);if(!h){shut();return}
if(String(window.getSelection?window.getSelection():''))return;if(P&&P.h===h)shut();else lift(h)});
document.addEventListener('focusin',function(e){var b=e.target;if(quiet||!b.classList||!b.classList.contains('xp-b'))return;var key=true;try{key=b.matches(':focus-visible')}catch(x){}if(key&&!is(wrap(b)))show(wrap(b),'focus')});
document.addEventListener('focusout',function(e){var t=e.target,w=wrap(t);if(!w)return;setTimeout(function(){if(t.isConnected&&is(w)&&O.h!=='hover'&&!w.contains(document.activeElement))hide()},0)});
document.addEventListener('keydown',function(e){if(e.key!=='Escape'||e.isComposing||!P)return;e.preventDefault();e.stopImmediatePropagation();shut()},true);
document.addEventListener('keydown',function(e){if(e.key!=='Escape'||e.isComposing||!O)return;var w=find(O.k);if(!w){O=null;return}
var p=w.lastElementChild;if(!p.getClientRects().length||window.getComputedStyle(p).visibility==='hidden'){hide();return}      // one nobody can see leaves the Escape to the page
e.preventDefault();e.stopImmediatePropagation();var inside=w.contains(document.activeElement);hide();if(inside)back(w.firstElementChild)},true);
window.addEventListener('resize',function(){var w=O&&find(O.k);if(w)place(w);put()});
window.addEventListener('scroll',put,true);document.addEventListener('transitionend',put,true);
function again(){if(!O)return;var w=find(O.k);if(w){set(w,true);place(w)}else O=null}
function both(){again();redrawn()}
document.addEventListener('stackshot:swapped',both);document.addEventListener('stackshot:redrawn',both)})();"""
SCRIPT = f"<script>{JS}</script>"
