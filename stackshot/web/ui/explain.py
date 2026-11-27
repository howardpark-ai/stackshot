"""ui/explain.py — the one "?" control that holds a page's explainer text.

Text that explains what a section is, or how something works, is not drawn on the page: it sits behind a small "?" next to the thing it explains (CONTRIBUTING.md, *Page
text*). `explain(key, text, what)` is the markup; CSS joins the shared stylesheet (render.Board._css) and SCRIPT ends every page's body (render._FAB_PAIR), so a page
that draws the board's chrome only has to call explain().

The popup opens on a tap or click, and on a desktop also on hover and on keyboard focus; Escape, a tap outside and tabbing away close it. The button's accessible
description is the text itself, so a screen reader says it on focus, open or not. The popup stays inside the window and inside any ancestor that clips it. The script
is delegated on the document and remembers the open popup by its key, so a block the home page's live refresh swaps in keeps it open."""
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
    """HTML: a heading with its "?" beside it on one line. `heading` is the whole heading element, `tip` what explain() gave; both are markup."""
    return f'<div class="xp-head">{heading}{tip}</div>'


# The button is a 36 px target (44 px for a finger) round an 18 px circle; the negative margin keeps that target from making a line of text taller. The popup sets every
# inherited text property itself, since it can sit in a heading.
CSS = """
.xp-head{display:flex;flex-wrap:wrap;align-items:center;column-gap:4px}.xp-head>h1,.xp-head>h2{margin-right:0}
.xp{position:relative;display:inline-block;vertical-align:middle;margin:-8px 0;line-height:1}
.xp-b{display:inline-flex;align-items:center;justify-content:center;width:36px;height:36px;margin:0;padding:0;border:0;border-radius:8px;background:none;color:var(--mut);font-family:inherit;cursor:pointer}
.xp-b>span{display:inline-flex;align-items:center;justify-content:center;box-sizing:border-box;width:18px;height:18px;border:1.5px solid currentColor;border-radius:50%;font-size:12px;font-weight:600;line-height:1}
.xp-b:hover,.xp-b[aria-expanded=true]{color:var(--fg)}.xp-b:focus-visible{outline:2px solid var(--acc);outline-offset:-2px;color:var(--fg)}
.xp-pop{position:absolute;top:100%;left:0;z-index:35;display:block;box-sizing:border-box;width:max-content;max-width:320px;padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);box-shadow:0 4px 16px rgba(0,0,0,.16);font-size:12px;font-style:normal;font-weight:400;line-height:1.5;letter-spacing:normal;text-transform:none;text-align:left;white-space:normal;overflow-wrap:anywhere;cursor:auto}
.xp-pop[hidden]{display:none}
@media(pointer:coarse){.xp{margin:-12px 0}.xp-b{width:44px;height:44px}}
"""

# O is the one open popup: {k: its key, h: how it opened ('hover', 'focus' or 'pin')}. A tap or click pins it; hover and focus never undo a pin.
JS = r"""(function(){var O=null,quiet=false;
function wrap(t){return t&&t.closest?t.closest('.xp'):null}
function find(k){return document.querySelector('.xp[data-xp="'+k+'"]')}
function set(w,on){w.firstElementChild.setAttribute('aria-expanded',String(on));w.lastElementChild.hidden=!on}
function place(w){var b=w.firstElementChild,p=w.lastElementChild,L=0,R=document.documentElement.clientWidth,H=window.innerHeight;
for(var n=w.parentElement;n&&n!==document.body&&n!==document.documentElement;n=n.parentElement)if(window.getComputedStyle(n).overflowX!=='visible'){var c=n.getBoundingClientRect();L=Math.max(L,c.left);R=Math.min(R,c.right)}
p.style.left='0px';p.style.top='0px';p.style.maxWidth=Math.max(0,Math.min(320,R-L-16))+'px';
var r=b.getBoundingClientRect(),o=w.getBoundingClientRect(),W=p.offsetWidth,h=p.offsetHeight,x=Math.max(L+8,Math.min(r.left+r.width/2-W/2,R-8-W)),y=r.bottom;
if(y+h>H-8&&r.top-h>=8)y=r.top-h;
p.style.left=(x-o.left)+'px';p.style.top=(y-o.top)+'px'}
function hide(){if(!O)return;var w=find(O.k);O=null;if(w)set(w,false)}
function show(w,how){var k=w.getAttribute('data-xp');if(O&&O.k!==k)hide();O={k:k,h:O&&O.h==='pin'?'pin':how};set(w,true);place(w)}
function is(w){return !!O&&O.k===w.getAttribute('data-xp')}
document.addEventListener('click',function(e){var w=wrap(e.target);if(!w||!e.target.closest('.xp-b'))return;e.preventDefault();if(is(w)&&O.h==='pin')hide();else show(w,'pin')});
document.addEventListener('pointerover',function(e){var w=wrap(e.target);if(w&&e.pointerType==='mouse'&&!w.contains(e.relatedTarget)&&!is(w))show(w,'hover')});
document.addEventListener('pointerout',function(e){var w=wrap(e.target);if(w&&e.pointerType==='mouse'&&!w.contains(e.relatedTarget)&&is(w)&&O.h==='hover')hide()});
document.addEventListener('pointerup',function(e){if(O&&wrap(e.target)!==find(O.k))hide()},true);
document.addEventListener('focusin',function(e){var b=e.target;if(quiet||!b.classList||!b.classList.contains('xp-b'))return;var key=true;try{key=b.matches(':focus-visible')}catch(x){}if(key&&!is(wrap(b)))show(wrap(b),'focus')});
document.addEventListener('focusout',function(e){var t=e.target,w=wrap(t);if(!w)return;setTimeout(function(){if(t.isConnected&&is(w)&&O.h!=='hover'&&!w.contains(document.activeElement))hide()},0)});
document.addEventListener('keydown',function(e){if(e.key!=='Escape'||e.isComposing||!O)return;var w=find(O.k);if(!w){O=null;return}e.preventDefault();e.stopPropagation();var inside=w.contains(document.activeElement);hide();
if(inside){quiet=true;w.firstElementChild.focus();quiet=false}},true);
window.addEventListener('resize',function(){var w=O&&find(O.k);if(w)place(w)});
document.addEventListener('stackshot:swapped',function(){if(!O)return;var w=find(O.k);if(w){set(w,true);place(w)}else O=null})})();"""
SCRIPT = f"<script>{JS}</script>"
