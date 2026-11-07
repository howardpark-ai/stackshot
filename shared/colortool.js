/* colortool v3 */
/*
 * SHARED SOURCE. This file is the one color tool that more than one app draws. The app that owns it keeps the original; another app pins a
 * VERBATIM copy of it (not an edited one) and passes its own settings in a cfg object. Change this file only with a version bump (the first
 * line and ColorTool.version) and tell the apps that pin a copy, so each can take the new version on purpose.
 *
 * What it does. A "Colors" button (a bare two-color circle, split by a diagonal line, with no text and no frame; its accessible name is "Colors") opens a panel above it. The bottom of the panel, next to the button, is one box
 * with the presets and the saved combinations (kept by the app's server); above it a Fields fold, closed at first, holds the 14 color fields (each a
 * color picker and a hex box that apply at once), and opening it grows the panel upward; the Preview box sits outside the fold, between the Fields button and the presets, so it stays in view. The look is applied by custom
 * properties set inline on <html> and kept in this browser (localStorage); whether the fields are open is kept there too, under storageKey + ':fields'. Dark theme only: in the light theme nothing is drawn and no stored look is applied (onApply still runs, with nothing stored).
 *
 * Entries (window.ColorTool):
 *   version                 the number of the line above (3).
 *   applyStored(cfg)        put in the head: injects cfg.css once and applies the stored look before the first paint; re-applies when the
 *                           page's data-theme or the system color scheme changes. Draws nothing.
 *   init(cfg)               put at the end of the body: calls applyStored first if it has not run, then builds the button in cfg.mount and
 *                           the panel in document.body (position: fixed, opening upward from the button, above everything).
 *   remount(mount, cfg?)    move the button into a new mount element after the app re-rendered its own (the panel and its state stay).
 *   engine(cfg)             the pure functions and constants of that cfg (resolve, norm, refuse, warn, load, save, apply, ratio, ...), for tests.
 *
 * cfg (per app):
 *   storageKey  the localStorage key of the applied look (a map of the fields that are set); the Fields fold is kept under storageKey + ':fields'.
 *   shipped     the 14 values in use with nothing set (an object), or a function returning it; a function is called on every apply, after the
 *               inline properties this file set were removed, and never cached. An optional 15th key, ifill, is the input fill. The five
 *               that follow others (labbg: text and links, background, cards; labfg, labbd: text and links; disbg: solid fill, background; disfg: solid
 *               fill, text on it, background) are the app's value while none of the fields they follow is set, and worked out from the live ones
 *               once one is; a key the app leaves out, or does not give as #rrggbb, is always worked out.
 *   vars        {field: [css custom properties]}: set inline to that field's resolved value whenever the field is set (Cards and Lines also when
 *               the page background is set, because they follow it).
 *   onApply     optional hook (resolved, stored, set, addClass, engine) run on every apply, after the tracked properties and classes were
 *               removed: Reset and Original orange theme included (stored is then {}) and the light theme too (resolved and stored are then {}, so it sets
 *               nothing unless it ignores them); set(prop, value) and addClass(name) are tracked, so Reset and Original orange theme remove everything set through them.
 *   isDark      optional function; the default reads data-theme, else prefers-color-scheme.
 *   gate        "refuse" (default: a change that breaks a readability pair is not applied) or "warn" (every pair is only a note with its ratio).
 *   text        optional {signIn, note, example}: the line shown when the saved list answers 403, the small note at the end of the panel, and
 *               the example hex in the 'six digits' hint; each has a neutral default.
 *   css         an extra stylesheet string, injected once.
 *   mount       selector or element that holds the button.
 *   preview     trusted HTML for the preview strip, rendered inert; without it the Preview box is left out.
 *   api         base URL of the saved list: GET -> {combos, max}, POST {name, values}, POST api + "/delete" {id}; without it that box is left out.
 *
 * The 14 fields: bg card line fg mut link ibd solid onsolid labbg labfg labbd disbg disfg. The panel reads the page's tokens --bg --card --line
 * --fg --mut --ibd and --ifill, and its classes and ids start with ct-. One tool per page.
 */
(function () {
  'use strict';
  var VERSION = 3;

  /* ---- constants ---- */
  /* the 14 fields in the order the panel lists them: [key, the row's name, its group] */
  var FIELDS = [['bg', 'Page background', 'Surfaces'], ['card', 'Cards', 'Surfaces'], ['line', 'Lines', 'Surfaces'],
    ['fg', 'Body text', 'Text'], ['mut', 'Muted text', 'Text'], ['link', 'Text and links', 'Text'],
    ['ibd', 'Button outlines', 'Buttons'], ['solid', 'Solid fills', 'Buttons'], ['onsolid', 'Text on solid fills', 'Buttons'], ['disbg', 'Disabled fill', 'Buttons'], ['disfg', 'Disabled text', 'Buttons'],
    ['labbg', 'Fill', 'Small labels'], ['labfg', 'Text', 'Small labels'], ['labbd', 'Outline', 'Small labels']];
  var KEYS = FIELDS.map(function (f) { return f[0]; });
  var GROUPS = [];
  FIELDS.forEach(function (f) { if (GROUPS.indexOf(f[2]) < 0) GROUPS.push(f[2]); });
  /* a field after the ones its unset value is made from (norm() walks it) */
  var ORDER = ['bg', 'fg', 'mut', 'ibd', 'link', 'solid', 'card', 'line', 'onsolid', 'labbg', 'labfg', 'labbd', 'disbg', 'disfg'];
  var FOLLOW = { card: 'bg', line: 'bg' };      /* these two follow a set page background, so their vars are set with it */
  var DK = '#161617', WH = '#ffffff';           /* the near-black and the white label (a free solid pick takes whichever reads better) */
  var LIMITS = { fg_bg: 11, fg_card: 7, mut: 4.5, ibd: 3, link: 4.5, solid: 3, onsolid: 4.5, lab: 4.5, labbd: 3, dis: 3, line: 1.15 };
  /* the fields a field follows when it is not set: it is the shipped value while none of them is set, else worked out from the live ones (resolve); the panel's "follows the others" is this table */
  var FOLLOWS = { card: ['bg'], line: ['bg'], onsolid: ['solid'], labbg: ['link', 'bg', 'card'], labfg: ['link'], labbd: ['link'], disbg: ['solid', 'bg'], disfg: ['solid', 'onsolid', 'bg'] };
  var HOVER = 14, PRESSED = 24;                 /* the main button's hover and pressed blends toward the text (toward black under a lighter label) */
  var NEUTRAL = { bg: '#161617', card: '#1f1f21', line: '#2c2c2e', fg: '#ececea', mut: '#a3a29d', ibd: '#929190', disbg: '#2a2a2c', disfg: '#a3a29d' };
  function preset(link, solid, onsolid, labbg, labfg) {
    var p = {}; Object.keys(NEUTRAL).forEach(function (k) { p[k] = NEUTRAL[k]; });
    p.link = link; p.solid = solid; p.onsolid = onsolid; p.labbg = labbg; p.labfg = labfg; p.labbd = labbg; return p;
  }
  /* [id, name, the combination]; the first is the empty map: nothing set, what the page ships (the original orange theme) */
  var PRESETS = [['live', 'Original orange theme', {}],
    ['sky', 'Sky', preset('#7cb7ff', '#2a6fd0', '#ffffff', '#14283f', '#7cb7ff')],
    ['mint', 'Mint', preset('#5fd3a6', '#18805d', '#ffffff', '#10302a', '#5fd3a6')],
    ['violet', 'Violet', preset('#b79cff', '#7a52e0', '#ffffff', '#251c46', '#b79cff')],
    ['rose', 'Rose', preset('#ff8fb0', '#d6336c', '#ffffff', '#40182a', '#ff8fb0')]];
  var PRE = {}; PRESETS.forEach(function (p) { PRE[p[0]] = p[2]; });

  /* ---- pure functions ---- */
  function ok(v) { return typeof v === 'string' && /^#[0-9a-f]{6}$/i.test(v); }
  function rgb(h) { return [1, 3, 5].map(function (i) { return parseInt(h.substr(i, 2), 16); }); }
  function hex(c) { return '#' + c.map(function (x) { return ('0' + Math.round(x).toString(16)).slice(-2); }).join(''); }
  function lum(h) { var c = rgb(h).map(function (x) { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); }); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; }
  function ratio(a, b) { var x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
  function mix(top, base, p) { var t = rgb(top), b = rgb(base); return hex(t.map(function (x, i) { return x * p / 100 + b[i] * (100 - p) / 100; })); }
  function fx(v) { return (Math.floor(v * 100) / 100).toFixed(2); }
  function label(c) { return ratio(DK, c) >= ratio(WH, c) ? DK : WH; }

  /* the pairs the gate checks first: [field, against, minimum, what, where] */
  var RF = [['fg', 'bg', LIMITS.fg_bg, 'body text', 'the page'], ['fg', 'card', LIMITS.fg_card, 'body text', 'cards'], ['mut', 'bg', LIMITS.mut, 'muted text', 'the page'],
    ['mut', 'card', LIMITS.mut, 'muted text', 'cards'], ['ibd', 'bg', LIMITS.ibd, 'button outlines', 'the page'], ['ibd', 'card', LIMITS.ibd, 'button outlines', 'cards']];

  /* ---- the text of the panel (three of the lines can be replaced by the app: cfg.text = {signIn, note, example}) ---- */
  var T = {
    storeOff: 'This browser does not allow saving here, so a pick has no effect.',
    savedOff: 'Saved combinations are not available right now.',
    savedOffline: 'Saved combinations are not available right now (offline?).',
    signIn: 'Sign in to use saved combinations.',
    needName: 'Give it a name first.',
    unreadable: 'This combination cannot be read.',
    note: 'Dark theme only. The look you apply is kept in this browser.',
    example: '#4a90d9'
  };

  /* ---- the stylesheet of the button and the panel ---- */
  var CSS = [
    '.ct{display:inline-block;font-size:13px;line-height:1.3}.ct[hidden]{display:none}',
    '.ct-btn,.ct-pop button.ct-b{font:inherit;color:var(--fg)}',
    '.ct-pop input.ct-pick,.ct-pop input.ct-hex{color:var(--fg)}',      /* no font here: the hex boxes keep their own 16 px (below it a phone zooms the page on focus) */
    '.ct-b{min-height:32px;padding:5px 12px;border:1px solid var(--ibd,var(--mut));border-radius:8px;background:var(--card);cursor:pointer}',
    '.ct-b:hover{border-color:var(--fg)}',
    '.ct-btn{display:inline-flex;align-items:center;justify-content:center;min-width:32px;padding:4px;border:0;border-radius:50%;background:none;font-size:13px;line-height:1.3}',
    '.ct-dot{flex:none;width:22px;height:22px;border-radius:50%;border:1px solid var(--ibd,var(--mut));background:linear-gradient(135deg,var(--ct-a,transparent) 50%,var(--ct-b,transparent) 50%)}',
    '.ct-btn:hover .ct-dot{border-color:var(--fg)}',
    '.ct-btn:focus-visible,.ct-pop .ct-b:focus-visible,.ct-pop .ct-pick:focus-visible,.ct-pop .ct-hex:focus-visible{outline:2px solid var(--fg);outline-offset:2px}',
    '.ct-pop{position:fixed;z-index:40;left:8px;bottom:8px;box-sizing:border-box;width:min(366px,calc(100vw - 16px));max-height:calc(100dvh - 16px);overflow-y:auto;overscroll-behavior:contain;padding:12px;background:var(--card);color:var(--fg);border:1px solid var(--ibd,var(--mut));border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.45);font-size:13px;line-height:1.3;text-align:left}',
    '.ct-pop[hidden]{display:none}',
    '.ct-box{margin:0 0 10px;padding:10px 12px;border:1px solid var(--line);border-radius:8px}',
    '.ct-gh{margin:0 0 8px;font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--ct-link,var(--fg))}',
    '.ct-fields{margin:0}.ct-fields[hidden]{display:none}',
    '.ct-rows{margin:0 0 0 14px}',
    '.ct-fold{display:flex;align-items:center;gap:8px;width:100%;margin:0 0 10px;text-align:left}.ct-fold::before{content:"";flex:none;width:6px;height:6px;margin:0 3px 0 2px;border-right:2px solid currentColor;border-bottom:2px solid currentColor;transform:rotate(-135deg)}.ct-fold[aria-expanded=true]::before{transform:rotate(45deg)}',
    '.ct-sec+.ct-sec{margin-top:12px;padding-top:12px;border-top:1px solid var(--line)}#ct-dock{margin-bottom:0}',
    '.ct-presets{display:flex;flex-wrap:wrap;gap:6px}',
    '.ct-preset{display:inline-flex;align-items:center;gap:6px}',
    '.ct-preset[aria-pressed=true]{border-color:var(--fg);box-shadow:inset 0 0 0 1px var(--fg)}',
    '.ct-preset.low{border-style:dashed}',
    '.ct-dots{display:inline-flex}.ct-dots i{width:10px;height:10px;margin-right:-2px;border-radius:50%;border:1px solid var(--ibd,var(--mut));background:var(--c)}',
    '.ct-row{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:0 8px;margin:0 0 8px}.ct-row:last-child{margin-bottom:0}',
    '.ct-rl{font-weight:600;min-width:0;overflow-wrap:anywhere}',
    '.ct-state{display:block;font-size:12px;font-weight:400;color:var(--mut)}',
    '.ct-ctl{display:flex;align-items:center;gap:6px}',
    '.ct-pick{width:34px;height:28px;padding:0;border:1px solid var(--ibd,var(--mut));border-radius:6px;background:none;cursor:pointer}',
    '.ct-hex{width:92px;padding:4px 6px;border:1px solid var(--ibd,var(--mut));border-radius:6px;background:var(--ifill,var(--card));font:16px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}',
    '.ct-note{grid-column:1/-1;margin:4px 0 0;font-size:12px;color:var(--mut);overflow-wrap:anywhere}.ct-note:empty{display:none}',
    '.ct-prev{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:0;padding:10px;border:1px solid var(--line);border-radius:8px;background:var(--bg)}',
    '.ct-cur{margin:8px 0 0;font-size:12px;color:var(--mut)}',
    '.ct-save{display:flex;gap:6px}.ct-save .ct-hex{flex:1 1 auto;width:auto;min-width:0;font-family:inherit}.ct-save .ct-b{flex:none;white-space:nowrap}',
    '.ct-list{list-style:none;margin:8px 0 0;padding:0}',
    '.ct-list li{display:flex;gap:6px;margin:0 0 6px}.ct-list li:last-child{margin-bottom:0}.ct-list .ct-use{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;text-align:left}',
    '.ct-foot{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px;margin:12px 0 0}',
    '.ct-small{margin:8px 0 0;font-size:12px;color:var(--mut)}',
    '@media(pointer:coarse){.ct-b{min-height:44px}.ct-btn{min-width:44px}.ct-pick{width:44px;height:44px}.ct-hex{min-height:44px}}',
    '@media print{.ct,.ct-pop{display:none}}'
  ].join('\n');

  /* ---- one engine per cfg ---- */
  var engines = [];
  function make(cfg) {
    var X = cfg.text && typeof cfg.text === 'object' ? cfg.text : {}, root = document.documentElement, KEY = cfg.storageKey, GATE = cfg.gate === 'warn' ? 'warn' : 'refuse';
    var SHIP = null, tracked = { props: {}, cls: {} }, started = false, wantUI = false, ui = null, mountRef = cfg.mount, cssIn = false, libIn = false;

    function shipNow() {
      var v = typeof cfg.shipped === 'function' ? cfg.shipped() : cfg.shipped;
      if (v && typeof v === 'object') SHIP = v; else if (!SHIP) SHIP = {};
      return SHIP;
    }
    function ship() { return SHIP || shipNow(); }
    /* the shipped values with a field the app left out (or all of them, when it answered with something that is not an object) read as black, so that nothing throws */
    function filled() { var S = ship(), o = {}; KEYS.concat(['ifill']).forEach(function (k) { o[k] = S[k] || '#000000'; }); return o; }
    function isDark() {
      if (typeof cfg.isDark === 'function') { try { return !!cfg.isDark(); } catch (e) { return false; } }
      var t = root.getAttribute('data-theme');
      return t ? t === 'dark' : !!(window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches);
    }

    /* the 14 values in use for a map of the fields that are set: a field not set is the shipped value, or follows the others
       (the card and lines the background, the label the text and links, the disabled pair the Send faded to 50%) once one of them is set */
    function resolve(s) {
      var S = filled(), A = ship(), r = {};
      /* the app's own shipped value of a field that follows others, while none of them is set (in lowercase, as a stored value is); a missing or malformed one is worked out */
      function own(k, worked) { return ok(A[k]) && !FOLLOWS[k].some(function (d) { return s[d]; }) ? A[k].toLowerCase() : worked; }
      r.bg = s.bg || S.bg; r.fg = s.fg || S.fg; r.mut = s.mut || S.mut; r.ibd = s.ibd || S.ibd; r.link = s.link || S.link; r.solid = s.solid || S.solid;
      r.card = s.card || (s.bg ? mix(r.fg, r.bg, 4) : S.card); r.line = s.line || (s.bg ? mix(r.fg, r.bg, 10) : S.line);
      r.onsolid = s.onsolid || (s.solid ? label(s.solid) : S.onsolid);
      r.labbg = s.labbg || own('labbg', mix(r.link, r.card, 16)); r.labfg = s.labfg || own('labfg', r.link); r.labbd = s.labbd || own('labbd', r.link);
      r.disbg = s.disbg || own('disbg', mix(r.solid, r.bg, 50)); r.disfg = s.disfg || own('disfg', mix(r.onsolid, r.bg, 50));
      r.ifill = s.bg ? mix(r.fg, r.bg, 10) : S.ifill;
      return r;
    }
    /* a map cleaned: only valid #rrggbb, lowercase, and no field equal to what it would be unset (walked in the order the unset values are made from) */
    function norm(o) {
      var s = {};
      ORDER.forEach(function (k) { if (o && ok(o[k])) { var v = o[k].toLowerCase(); if (v !== resolve(s)[k]) s[k] = v; } });
      return s;
    }
    /* the gate: REFUSE pairs (the change is not applied; none in the "warn" gate) and WARN pairs (applied, with a note); the numbers are LIMITS */
    function refuse(r) {
      var o = [];
      if (GATE === 'warn') return o;
      RF.forEach(function (p) { var v = ratio(r[p[0]], r[p[1]]); if (v < p[2]) o.push(p[3] + ' would read ' + fx(v) + ':1 on ' + p[4] + ' (' + p[2] + ':1 needed)'); });
      return o;
    }
    function lighter(s, r) { return !!((s.solid || s.onsolid) && lum(r.onsolid) > lum(r.solid)); }
    function warn(r, s) {
      var o = [], far = lighter(s || {}, r) ? '#000000' : r.fg;
      function w(k, a, b, min, t) { var v = ratio(a, b); if (v < min) o.push({ k: k, t: fx(v) + ':1 ' + t + ' (below ' + min + ':1)' }); }
      if (GATE === 'warn') RF.forEach(function (p) { w(p[0], r[p[0]], r[p[1]], p[2], p[3] + ' on ' + p[4]); });
      w('link', r.link, r.bg, LIMITS.link, 'on the page'); w('link', r.link, r.card, LIMITS.link, 'on cards');
      w('solid', r.solid, r.bg, LIMITS.solid, 'against the page'); w('solid', r.solid, r.card, LIMITS.solid, 'against cards');
      w('onsolid', r.onsolid, r.solid, LIMITS.onsolid, 'at rest'); w('onsolid', r.onsolid, mix(far, r.solid, HOVER), LIMITS.onsolid, 'hovered'); w('onsolid', r.onsolid, mix(far, r.solid, PRESSED), LIMITS.onsolid, 'pressed');
      w('labfg', r.labfg, r.labbg, LIMITS.lab, 'on the label fill'); if (r.labbd !== r.labbg) w('labbd', r.labbd, r.card, LIMITS.labbd, 'against cards');
      w('disfg', r.disfg, r.disbg, LIMITS.dis, 'on the disabled fill'); w('line', r.line, r.card, LIMITS.line, 'against cards: lines would disappear');
      return o;
    }
    /* the stored look: a valid map, an older {text} read as link; one that fails the REFUSE gate (hand-edited, or stored by an older version) is ignored and
       cleared at load, its surface and text fields. The "warn" gate never clears. */
    function load() {
      var s = {}, bad = false;
      try {
        var o = JSON.parse(localStorage.getItem(KEY) || '{}');
        if (o && typeof o === 'object') {
          if (ok(o.text) && !ok(o.link)) o.link = o.text;
          s = norm(o);
          if (refuse(resolve(s)).length) { ['bg', 'card', 'fg', 'mut', 'ibd'].forEach(function (k) { delete s[k]; }); s = norm(s); bad = true; }
        }
      } catch (e) { }
      if (bad) save(s);
      return s;
    }
    function save(s) { try { if (Object.keys(s).length) localStorage.setItem(KEY, JSON.stringify(s)); else localStorage.removeItem(KEY); } catch (e) { } }
    /* the Fields fold: closed unless this browser kept it open (storage that is off or full leaves it closed) */
    var FOLD = KEY + ':fields';
    function foldRead() { try { return localStorage.getItem(FOLD) === '1'; } catch (e) { return false; } }
    function foldWrite(on) { try { if (on) localStorage.setItem(FOLD, '1'); else localStorage.removeItem(FOLD); } catch (e) { } }

    /* apply: take off everything this file set, read the shipped values, then set the stored look (dark only) */
    function apply() {
      var st = root.style, c = root.classList;
      Object.keys(tracked.props).forEach(function (p) { st.removeProperty(p); }); tracked.props = {};
      Object.keys(tracked.cls).forEach(function (k) { c.remove(k); }); tracked.cls = {};
      shipNow();
      var dk = isDark(), s = dk ? load() : {}, r = dk ? resolve(s) : {};
      var set = function (p, v) { tracked.props[p] = 1; st.setProperty(p, v); }, add = function (k) { tracked.cls[k] = 1; c.add(k); };
      if (dk) KEYS.forEach(function (k) {
        if ((s[k] || (FOLLOW[k] && s[FOLLOW[k]])) && cfg.vars && cfg.vars[k]) cfg.vars[k].forEach(function (p) { set(p, r[k]); });
      });
      if (typeof cfg.onApply === 'function') cfg.onApply(r, s, set, add, api);
      syncUI(dk, r);
    }

    function start() {
      if (started) return;
      started = true;
      if (cfg.css && !cssIn) { cssIn = true; inject(cfg.css); }
      apply();
      if (window.MutationObserver) new MutationObserver(apply).observe(root, { attributes: true, attributeFilter: ['data-theme'] });
      try { var m = matchMedia('(prefers-color-scheme: dark)'); if (m.addEventListener) m.addEventListener('change', apply); else if (m.addListener) m.addListener(apply); } catch (e) { }
    }
    /* a style put in the head by the script, so the page's own style element stays the first */
    function inject(text) { var e = document.createElement('style'); e.textContent = text; (document.head || root).appendChild(e); }

    /* ---- the button and the panel ---- */
    function mountEl() {
      var m = mountRef;
      if (typeof m === 'string') m = document.querySelector(m);
      return m && m.appendChild ? m : null;
    }
    function el(tag, props, kids) {
      var e = document.createElement(tag);
      Object.keys(props || {}).forEach(function (k) {
        if (k === 'className') e.className = props[k]; else if (k === 'text') e.textContent = props[k]; else e.setAttribute(k, props[k]);
      });
      (kids || []).forEach(function (c) { e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
      return e;
    }
    function live(id, cls, text) { return el('p', { className: cls || 'ct-note', id: id, role: 'status', 'aria-live': 'polite', text: text || '' }); }
    function box(id, title, kids) {
      var g = el('div', { className: 'ct-gh', id: id, text: title });
      return el('div', { className: 'ct-box', role: 'group', 'aria-labelledby': id }, [g].concat(kids));
    }
    function syncUI(dk, r) {
      if (!wantUI) return;
      if (!dk) { if (ui) { ui.wrap.hidden = true; ui.close(); } return; }
      if (!ui) buildUI();
      if (ui) { ui.wrap.hidden = false; ui.paint(r); }
    }
    function mountUI() {
      wantUI = true;
      if (!isDark()) return;
      if (mountEl()) buildUI();
      else if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { if (isDark() && !ui) { buildUI(); if (ui) ui.paint(resolve(load())); } });
    }
    function remount(m) {
      mountRef = m;
      if (ui) { var t = mountEl(); if (t) { t.appendChild(ui.wrap); ui.place(); } } else if (wantUI && isDark() && mountEl()) { buildUI(); if (ui) ui.paint(resolve(load())); }
    }

    function buildUI() {
      var mount = mountEl();
      if (!mount || ui) return;
      if (!libIn) { libIn = true; inject(CSS); }
      var $ = function (id) { return document.getElementById(id); };
      var say = function (id, t) { var e = $(id); if (e && e.textContent !== t) e.textContent = t; };
      function txt(e, t) { if (e.textContent !== t) e.textContent = t; }
      var API = cfg.api;
      var rows = {}, sticky = null, combos = [], delArm = null, delTimer = 0;

      /* the button: a bare circle, the live page color above the diagonal and the live solid fill below it; no text, so it is named by aria-label */
      var dot = el('span', { className: 'ct-dot', 'aria-hidden': 'true' });
      var btn = el('button', { type: 'button', className: 'ct-b ct-btn', id: 'ct-btn', 'aria-label': 'Colors', title: 'Colors', 'aria-expanded': 'false', 'aria-controls': 'ct-pop' }, [dot]);
      var wrap = el('div', { className: 'ct', id: 'ct' }, [btn]);
      mount.appendChild(wrap);

      /* the panel: one box for each group */
      var pop = el('div', { className: 'ct-pop', id: 'ct-pop', role: 'group', 'aria-label': 'Colors' });
      pop.hidden = true;
      var presets = el('div', { className: 'ct-presets' });
      PRESETS.forEach(function (p) {
        var b = el('button', { type: 'button', className: 'ct-b ct-preset', 'data-p': p[0], 'data-n': p[1], 'aria-pressed': 'false' }, [el('span', { className: 'ct-dots', 'aria-hidden': 'true' }, [el('i'), el('i'), el('i'), el('i')]), p[1]]);
        presets.appendChild(b);
      });
      var boxes = [], previewBox = null;
      GROUPS.forEach(function (g) {
        var kids = FIELDS.filter(function (f) { return f[2] === g; }).map(function (f) {
          var k = f[0], full = g === 'Small labels' ? 'Small label ' + f[1].toLowerCase() : f[1];
          var row = el('div', { className: 'ct-row', 'data-k': k }, [
            el('div', { className: 'ct-rl' }, [el('label', { for: 'ct-h-' + k, id: 'ct-l-' + k, text: f[1] }), el('span', { className: 'ct-state', id: 'ct-s-' + k, text: 'shipped' })]),
            el('div', { className: 'ct-ctl' }, [
              el('input', { type: 'color', className: 'ct-pick', id: 'ct-p-' + k, value: filled()[k], 'aria-label': full + ': pick any color' }),
              el('input', { type: 'text', className: 'ct-hex', id: 'ct-h-' + k, value: filled()[k], maxlength: '7', spellcheck: 'false', autocomplete: 'off', autocapitalize: 'off', 'aria-label': full + ': six hex digits' })]),
            live('ct-n-' + k)]);
          return row;
        });
        boxes.push(box('ct-g-' + g.toLowerCase().replace(/ /g, '-'), g, [el('div', { className: 'ct-rows' }, kids)]));
      });
      if (cfg.preview) {
        var prev = el('div', { className: 'ct-prev', 'aria-hidden': 'true' });
        prev.setAttribute('inert', '');
        prev.innerHTML = cfg.preview;      /* the app's own trusted markup; the only innerHTML of this file */
        previewBox = box('ct-g-preview', 'Preview', [prev]);
      }
      /* the fields fold away above; the preview stays outside the fold, under the Fields button; the presets and the saved combinations sit together at the bottom, beside the button */
      var fields = el('div', { className: 'ct-fields', id: 'ct-fields' }, boxes);
      fields.hidden = true;
      var foldBtn = el('button', { type: 'button', className: 'ct-b ct-fold', id: 'ct-fold', 'aria-expanded': 'false', 'aria-controls': 'ct-fields', text: 'Fields' });
      var secs = [el('div', { className: 'ct-sec', role: 'group', 'aria-labelledby': 'ct-g-presets' }, [el('div', { className: 'ct-gh', id: 'ct-g-presets', text: 'Presets' }), presets, live('ct-n-presets'), live('ct-cur', 'ct-cur', 'Now: Original orange theme'), live('ct-n-store')])];
      if (API) {
        var cnt = el('span', { id: 'ct-cnt' });
        var head = el('div', { className: 'ct-gh', id: 'ct-g-saved' }, ['Saved combinations ', cnt]);
        secs.push(el('div', { className: 'ct-sec', id: 'ct-saved', role: 'group', 'aria-labelledby': 'ct-g-saved' }, [head,
          el('div', { className: 'ct-save' }, [el('input', { type: 'text', className: 'ct-hex', id: 'ct-name', maxlength: '40', placeholder: 'Name', spellcheck: 'false', autocomplete: 'off', 'aria-label': 'Name for this combination' }),
            el('button', { type: 'button', className: 'ct-b', id: 'ct-save', text: 'Save' })]),
          live('ct-n-saved'), el('ul', { className: 'ct-list', id: 'ct-list' })]));
      }
      pop.appendChild(fields);
      pop.appendChild(foldBtn);
      if (previewBox) pop.appendChild(previewBox);
      pop.appendChild(el('div', { className: 'ct-box', id: 'ct-dock' }, secs));
      pop.appendChild(el('div', { className: 'ct-foot' }, [el('button', { type: 'button', className: 'ct-b', id: 'ct-reset', text: 'Reset' })]));
      pop.appendChild(el('p', { className: 'ct-small', text: X.note || T.note }));
      document.body.appendChild(pop);
      KEYS.forEach(function (k) { rows[k] = { pick: $('ct-p-' + k), hex: $('ct-h-' + k), state: $('ct-s-' + k), note: $('ct-n-' + k) }; });

      function same(a, b) { return KEYS.every(function (k) { return a[k] === b[k]; }); }
      function copy(s) { var n = {}; KEYS.forEach(function (k) { if (s[k]) n[k] = s[k]; }); return n; }
      function refresh() {
        var s = load(), r = resolve(s), w = warn(r, s), by = {}, cur = 'Custom', S = filled();
        w.forEach(function (x) { (by[x.k] = by[x.k] || []).push(x.t); });
        KEYS.forEach(function (k) {
          var e = rows[k]; e.pick.value = r[k]; if (document.activeElement !== e.hex) e.hex.value = r[k];
          txt(e.state, s[k] ? '' : (FOLLOWS[k] && FOLLOWS[k].some(function (d) { return s[d]; }) ? 'follows the others' : 'shipped'));
          txt(e.note, sticky && sticky.k === k ? sticky.t : (by[k] ? 'Below its limit: ' + by[k].join('; ') + '.' : ''));
        });
        pop.querySelectorAll('.ct-preset').forEach(function (b) {
          var id = b.getAttribute('data-p'), pn = norm(PRE[id]), pr = resolve(pn), low = warn(pr, pn).length, on = same(pr, r);
          b.setAttribute('aria-pressed', on ? 'true' : 'false'); b.classList.toggle('low', low > 0);
          b.setAttribute('aria-label', b.getAttribute('data-n') + (low ? ', ' + low + ' pair' + (low > 1 ? 's' : '') + ' below their limit' : '')); if (on) cur = b.getAttribute('data-n');
          var v = {}; KEYS.forEach(function (k) { v[k] = PRE[id][k] || S[k]; });
          var ds = b.querySelectorAll('.ct-dots i');      /* built once: a rebuilt dot would be gone from the page before a click on it reaches the handlers */
          ['bg', 'card', 'link', 'solid'].forEach(function (k, j) { ds[j].style.setProperty('--c', v[k]); });
        });
        say('ct-cur', 'Now: ' + cur);
      }
      /* storage that is off or full keeps nothing, and apply() reads only storage: say so, one line, instead of a pick that seems to do nothing */
      function kept(s) { var good = JSON.stringify(load()) === JSON.stringify(s); say('ct-n-store', good ? '' : T.storeOff); return good; }
      /* every change goes through here: the new map is cleaned, gated on the resolved combination and, if it passes, stored and applied; a refusal names the pair and changes nothing */
      function commit(n, k) {
        n = norm(n); var bad = refuse(resolve(n));
        if (bad.length) { sticky = { k: k || '_', t: 'Not applied: ' + bad.join('; ') + '.' }; if (!k) say('ct-n-presets', sticky.t); refresh(); return false; }
        sticky = null; say('ct-n-presets', ''); save(n); kept(n); apply(); refresh(); return true;
      }
      function put(k, v) { var n = copy(load()); n[k] = v.toLowerCase(); commit(n, k); }

      /* placing: from the button's rectangle, upward; fixed in the body, so no scroll of the side panel clips it */
      function place() {
        if (pop.hidden) return;
        var rc = btn.getBoundingClientRect(), vw = root.clientWidth, vh = root.clientHeight || window.innerHeight;
        if (!rc.width && !rc.height) return;
        var w = Math.min(366, vw - 16), left = Math.max(8, Math.min(rc.left, vw - w - 8)), above = rc.top - 16, below = vh - rc.bottom - 16;
        pop.style.left = left + 'px';
        if (above < 160 && below > above) { pop.style.bottom = 'auto'; pop.style.top = (rc.bottom + 8) + 'px'; pop.style.maxHeight = Math.max(120, below) + 'px'; }
        else { pop.style.top = 'auto'; pop.style.bottom = (vh - rc.top + 8) + 'px'; pop.style.maxHeight = Math.max(120, above) + 'px'; }
      }
      /* the panel hangs from the button, so the fields open upward; keep the foot (the fold, the presets, the saved list) in view */
      function toEnd() { pop.scrollTop = pop.scrollHeight; }
      function atEnd() { return pop.scrollTop + pop.clientHeight >= pop.scrollHeight - 2; }
      /* an answer that adds a line to a panel scrolled to its end leaves it there; one that arrives after the person scrolled up does not move it. Decided when the answer arrives, before it is drawn */
      function keepEnd(fn) { var stick = atEnd(); fn(); if (stick) toEnd(); }
      function fold(on, keep) {
        fields.hidden = !on; foldBtn.setAttribute('aria-expanded', on ? 'true' : 'false');
        if (keep) foldWrite(on);
        if (!pop.hidden) { place(); toEnd(); }
      }
      function open(on) {
        pop.hidden = !on; sticky = null; btn.setAttribute('aria-expanded', on ? 'true' : 'false');
        if (on) { fold(foldRead(), false); refresh(); list(); place(); toEnd(); }
      }

      /* the saved list: one read when the panel opens, then each answer of a save or a delete replaces it */
      function msg(x) { return x && x.msg ? x.msg : T.savedOff; }
      function call(path, body) {
        return fetch(API + path, { method: body ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store', headers: body ? { 'Accept': 'application/json', 'Content-Type': 'application/json' } : { 'Accept': 'application/json' }, body: body ? JSON.stringify(body) : undefined })
          .then(function (r) {
            return r.text().then(function (t) {
              var d = null; try { d = JSON.parse(t); } catch (e) { }
              if (r.ok && d && Array.isArray(d.combos)) return d;
              throw { msg: d && d.error ? d.error : (r.status === 403 ? (X.signIn || T.signIn) : T.savedOff) };
            });
          }, function () { throw { msg: T.savedOffline }; });
      }
      function draw(d) {
        combos = d.combos; var ul = $('ct-list'); ul.textContent = '';
        combos.forEach(function (c) {
          var li = document.createElement('li'), a = document.createElement('button'), x = document.createElement('button');
          a.type = 'button'; a.className = 'ct-b ct-use'; a.setAttribute('data-id', c.id); a.textContent = c.name; a.title = c.name;
          x.type = 'button'; x.className = 'ct-b ct-del'; x.setAttribute('data-id', c.id); x.textContent = 'Delete'; x.setAttribute('aria-label', 'Delete ' + c.name); li.appendChild(a); li.appendChild(x); ul.appendChild(li);
        });
        say('ct-cnt', combos.length + ' of ' + (d.max || 50) + ' saved'); delArm = null;
      }
      function list() {
        if (!API) return; say('ct-n-saved', '');
        call('').then(function (d) { keepEnd(function () { draw(d); }); }, function (x) { keepEnd(function () { say('ct-n-saved', msg(x)); $('ct-list').textContent = ''; say('ct-cnt', ''); }); });
      }
      function saveNow() {
        var name = $('ct-name').value.trim(); if (!name) { say('ct-n-saved', T.needName); return; }
        var r = resolve(load()), v = {}; KEYS.forEach(function (k) { v[k] = r[k]; }); var had = combos.some(function (c) { return c.name.toLowerCase() === name.toLowerCase(); });
        call('', { name: name, values: v }).then(function (d) { keepEnd(function () { draw(d); say('ct-n-saved', (had ? 'Replaced ' : 'Saved ') + name + '.'); }); }, function (x) { keepEnd(function () { say('ct-n-saved', msg(x)); }); });
      }
      function useNow(id) {
        var c = combos.filter(function (x) { return x.id === id; })[0]; if (!c) return;
        var good = KEYS.every(function (k) { return c.values && /^#[0-9a-f]{6}$/i.test(c.values[k]); });
        if (!good) { say('ct-n-saved', T.unreadable); return; }
        if (commit(copy(c.values), null)) say('ct-n-saved', 'Applied ' + c.name + '.');
        else { say('ct-n-saved', c.name + ': ' + (sticky ? sticky.t : 'Not applied.')); var n = $('ct-n-saved'); if (n.scrollIntoView) n.scrollIntoView({ block: 'nearest' }); }
      }
      function delNow(b) {
        var id = b.getAttribute('data-id');
        if (delArm !== id) {
          delArm = id; $('ct-list').querySelectorAll('.ct-del').forEach(function (x) { if (x !== b) x.textContent = 'Delete'; });
          b.textContent = 'Delete?'; clearTimeout(delTimer); delTimer = setTimeout(function () { if (delArm === id) { delArm = null; b.textContent = 'Delete'; } }, 4000); return;
        }
        clearTimeout(delTimer); delArm = null; call('/delete', { id: id }).then(function (d) { keepEnd(function () { draw(d); say('ct-n-saved', 'Deleted.'); }); }, function (x) { keepEnd(function () { say('ct-n-saved', msg(x)); }); });
      }

      btn.addEventListener('click', function () { open(pop.hidden); });
      pop.addEventListener('click', function (e) {
        var t = e.target.closest ? e.target.closest('button') : null; if (!t || !pop.contains(t)) return;
        if (t.id === 'ct-fold') fold(foldBtn.getAttribute('aria-expanded') !== 'true', true);
        else if (t.classList.contains('ct-preset')) commit(copy(PRE[t.getAttribute('data-p')]), null);
        else if (t.classList.contains('ct-use')) useNow(t.getAttribute('data-id'));
        else if (t.classList.contains('ct-del')) delNow(t);
        else if (t.id === 'ct-save') saveNow();
      });
      pop.addEventListener('input', function (e) {
        var i = e.target; if (!i || !i.classList) return; var rw = i.closest('.ct-row'), k = rw && rw.getAttribute('data-k'); if (!k) return;
        if (i.classList.contains('ct-pick')) put(k, i.value);
        else if (i.classList.contains('ct-hex') && /^#?[0-9a-f]{6}$/i.test(i.value.trim())) put(k, '#' + i.value.trim().replace('#', ''));
      });
      pop.addEventListener('change', function (e) {
        var i = e.target; if (!i || !i.classList || !i.classList.contains('ct-hex') || !i.closest('.ct-row')) return;
        var k = i.closest('.ct-row').getAttribute('data-k'), v = i.value.trim().replace('#', '');
        if (/^[0-9a-f]{3}$/i.test(v)) v = v.replace(/./g, function (c) { return c + c; });
        if (/^[0-9a-f]{6}$/i.test(v)) { put(k, '#' + v); i.value = resolve(load())[k]; }
        else { sticky = { k: k, t: 'Use six digits like ' + (X.example || T.example) + '.' }; i.value = resolve(load())[k]; refresh(); }
      });
      $('ct-reset').addEventListener('click', function () { save({}); apply(); sticky = null; say('ct-n-store', ''); say('ct-n-presets', ''); refresh(); });
      document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !pop.hidden) { e.stopPropagation(); open(false); btn.focus(); } }, true);
      /* in the capture phase and by the event's path, decided before any handler can change the page: a click anywhere but this button and this panel closes it */
      document.addEventListener('click', function (e) {
        if (pop.hidden) return;
        var path = e.composedPath ? e.composedPath() : [], t = e.target;
        var inside = path.length ? path.indexOf(pop) >= 0 || path.indexOf(wrap) >= 0 : pop.contains(t) || wrap.contains(t);
        if (!inside) open(false);
      }, true);
      window.addEventListener('resize', place);
      window.addEventListener('scroll', place, true);

      ui = {
        wrap: wrap, pop: pop, btn: btn, place: place, close: function () { if (!pop.hidden) open(false); },
        paint: function (r) { btn.style.setProperty('--ct-a', r.bg); btn.style.setProperty('--ct-b', r.solid); pop.style.setProperty('--ct-link', r.link); if (!pop.hidden) refresh(); }
      };
      refresh();
      ui.paint(resolve(load()));
    }

    var api = {
      KEYS: KEYS, FIELDS: FIELDS, GROUPS: GROUPS, ORDER: ORDER, PRE: PRE, PRESETS: PRESETS, LIM: LIMITS, DK: DK, WH: WH, HOVER: HOVER, PRESSED: PRESSED, KEY: KEY, GATE: GATE, FOLLOWS: FOLLOWS,
      ship: ship, load: load, save: save, apply: apply, resolve: resolve, norm: norm, refuse: refuse, warn: warn, lighter: lighter, isDark: isDark,
      ratio: ratio, mix: mix, fx: fx, label: label, lum: lum
    };
    return { cfg: cfg, api: api, start: start, mountUI: mountUI, remount: remount };
  }
  function get(cfg) {
    for (var i = 0; i < engines.length; i++) if (engines[i].cfg === cfg) return engines[i];
    var e = make(cfg); engines.push(e); return e;
  }

  window.ColorTool = {
    version: VERSION,
    applyStored: function (cfg) { get(cfg).start(); },
    init: function (cfg) { var e = get(cfg); e.start(); e.mountUI(); },
    remount: function (mount, cfg) { var e = cfg ? get(cfg) : engines[engines.length - 1]; if (e) e.remount(mount); },
    engine: function (cfg) { return get(cfg).api; }
  };
})();
