"""anchorhub.notion — Notion pages and databases: webhook push where the connection can see the page, polling where it cannot."""
import json, os, hmac, hashlib, queue, threading, time
from datetime import datetime, timezone
from .core import Hub, ENVF, HEALTH, _cfg, _ts, guarded_loop, log, now_iso, now_iso_at, read_env, watches_load, watches_save

NPOLL = 5
ROUTES = ("/hook/notion",)   # the webhook run() registers; answered 503, not 404, while the start is being retried
def run(hub: Hub):
    import urllib.request
    env = read_env()
    tok = env.get("NOTION_TOKEN", "").strip()
    if not tok: log.warning("notion: no NOTION_TOKEN in %s", ENVF); return
    def api(path, body=None, ver="2022-06-28"):
        req = urllib.request.Request("https://api.notion.com/v1" + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {tok}", "Notion-Version": ver, "Content-Type": "application/json"},
                                     method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=20) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = int(e.headers.get("Retry-After") or 5); log.warning("notion: 429, backing off %ss", wait); time.sleep(wait)
            raise
    users = {}
    def uname(u):
        uid = (u or {}).get("id")
        if not uid: return "someone"
        if uid not in users:
            try: users[uid] = api(f"/users/{uid}").get("name") or uid
            except Exception: users[uid] = (u or {}).get("name") or uid
        return users[uid]
    me_ids = set()
    try:
        me = api("/users/me")
        if me.get("type") == "person": me_ids.add(me["id"])
        owner = ((me.get("bot") or {}).get("owner") or {}).get("user") or {}   # personal access token → bot owned by the owner
        if owner.get("id"): me_ids.add(owner["id"])
        for u in api("/users").get("results", []):
            if u.get("type") == "person" and (u.get("person") or {}).get("email") in set(_cfg.get("anchor_hub", "self_emails") or []): me_ids.add(u["id"])
    except Exception: pass
    if env.get("NOTION_HOOK_TOKEN", "").strip():   # a personal access token may not list or read other users; the webhook
        try:                                       # connection may, so notices name people instead of printing their ids
            req = urllib.request.Request("https://api.notion.com/v1/users?page_size=100", headers={"Authorization": f"Bearer {env['NOTION_HOOK_TOKEN'].strip()}", "Notion-Version": "2022-06-28"})
            with urllib.request.urlopen(req, timeout=20) as r:
                for u in json.load(r).get("results", []): users[u["id"]] = u.get("name") or u["id"]
        except Exception as e: log.warning("notion: user names unavailable (%s)", str(e)[:80])
    def system(u): return str((u or {}).get("id", "")).startswith("00000000-0000-0000-0000-")   # Notion's own actor (automations, recomputes), not a person
    def title_of(pg):
        for v in (pg.get("properties") or {}).values():
            if v.get("type") == "title": return "".join(t.get("plain_text", "") for t in v.get("title", [])) or "(untitled)"
        return "(untitled)"
    # ---- database anchors (watch a whole database, such as a "Roadmap") ----
    # A notion:<id> anchor may name a database: a row added or edited, or a comment on a row, is a notice on the
    # database's anchor. A row is a page whose parent is the database (or its data source, in newer webhook payloads).
    kinds: dict[str, bool] = {}        # id → is a database (cached once Notion has answered)
    dbs: dict[str, dict] = {}          # database id → {title, url, sources, base, last_iso, rows: {row id → {edited, comments}}}
    row_parent: dict[str, str] = {}    # page id → its parent's id (from webhook payloads, else one pages.retrieve)
    def is_db(i):
        if i in kinds: return kinds[i]
        try: api(f"/databases/{i}"); kinds[i] = True
        except urllib.error.HTTPError as e:
            if e.code in (400, 404): kinds[i] = False
            return False
        except Exception: return False
        return True
    def dbstate(db):
        st = dbs.get(db)
        if st is None:
            d = api(f"/databases/{db}"); t = int(time.time() // 60 * 60)   # Notion's edit times are whole minutes
            st = dbs[db] = {"title": "".join(x.get("plain_text", "") for x in d.get("title", [])) or "(untitled)", "url": d.get("url"),
                            "sources": set(), "base": float(t), "rows": {},
                            "last_iso": datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")}
            try: st["sources"] = {x["id"].replace("-", "") for x in api(f"/databases/{db}", ver="2025-09-03").get("data_sources", [])}
            except Exception: pass
        return st
    def parent_of(x):
        """(parent id, parent type) of a page or block — from a webhook payload when one named it, else one API read."""
        if x in row_parent: return row_parent[x]
        for path in (f"/pages/{x}", f"/blocks/{x}"):
            try: par = api(path).get("parent") or {}
            except Exception: continue
            typ = par.get("type", ""); v = par.get(typ)
            row_parent[x] = ((v if isinstance(v, str) else "").replace("-", ""), typ); return row_parent[x]
        return None
    def climb(pid, pages, db_ids):
        """Watched anchors above a page: [("page", anchor, None) | ("db", database, row)]. A subpage of a row, or of a watched
        page, belongs to it at any depth."""
        hits, cur = [], pid
        for _ in range(8):
            p = parent_of(cur)
            if not p or not p[0]: break
            up = p[0]
            d = next((d for d in db_ids if up == d or up in dbstate(d)["sources"]), None)
            if d: hits.append(("db", d, cur)); break          # cur is the row
            if up in pages: hits.append(("page", up, None))
            cur = up
        return hits
    t0 = float(int(time.time() // 60 * 60))   # a page anchor's subpages count from the receiver's start
    children: dict[tuple, dict] = {}           # (anchor, page id) → {edited, comments}
    def check_child(anc, cid, base, row=None):
        """A page below a watched page or below a row of a watched database: new comments, and its edit or creation."""
        with hub.lock: name = (hub.status["anchors"].get(f"notion:{anc}") or {}).get("title") or f"{anc[:8]}…"
        where = ""
        if row:
            try: where = f" (in the row \"{title_of(api(f'/pages/{row}'))[:60]}\")"
            except Exception: pass
        return scan(f"notion:{anc}", cid, children, (anc, cid), base=base, name=name, lead=True, noun="subpage", where=where)
    def mine(x, field): return ((x.get(field) or {}).get("id") in me_ids and not os.environ.get("ANCHOR_HUB_ALLOW_SELF")) or system(x.get(field))
    def scan(anchor, pid, slot, key, *, base=0.0, seed_all=False, name=None, lead=False, noun="page", where="", tag="",
             tag_comments=False, skip_trashed=True, since=None):
        """One page-like thing — a watched page, a row of a watched database, a page below either — against its saved state
        slot[key] = {edited, comments}: new comments, and an edit (for a row or subpage also its creation), by other people.
        The callers differ only in what they call the thing, where its state lives and from when changes count: `base` is the
        time from which an edit counts and before which comments are taken as already seen on first sight (seed_all instead
        takes everything as seen, with no notice); `since` also drops comments older than a catch-up's start. Until an earlier change
        this logic existed four times (check_page, check_row, check_child, the catch-up). → the number of notices raised."""
        pg = api(f"/pages/{pid}")
        if skip_trashed and (pg.get("in_trash") or pg.get("archived")): return 0
        cm = api(f"/comments?block_id={pid}&page_size=100").get("results", [])
        st = slot.get(key)
        if st is None:
            if seed_all: slot[key] = {"edited": pg.get("last_edited_time"), "comments": {c["id"] for c in cm}}; return 0
            st = slot[key] = {"edited": None, "comments": {c["id"] for c in cm if _ts(c.get("created_time")) < base}}
        title = title_of(pg); url = pg.get("url", f"https://www.notion.so/{pid}"); name = name or f"\"{title[:60]}\""; n = 0      # name = the anchor's title for the notice; `title` is this page's own
        on = f"on \"{title[:60]}\"{where}: " if lead else ""
        for c in cm:
            if c["id"] in st["comments"]: continue
            st["comments"].add(c["id"])
            if mine(c, "created_by") or (since is not None and _ts(c.get("created_time")) < since): continue
            text = "".join(t.get("plain_text", "") for t in c.get("rich_text", []))
            hub.event(anchor, {"title": name, "who": uname(c.get("created_by")), "url": url, "ts": c.get("created_time"),
                               "text": (tag if tag_comments else "") + on + text[:140] + ("…" if len(text) > 140 else "")}, kind="notion"); n += 1
        ed = pg.get("last_edited_time")
        if ed != st["edited"] and _ts(ed) >= base:
            new = noun != "page" and st["edited"] is None and _ts(pg.get("created_time")) >= base
            by = "created_by" if new else "last_edited_by"      # a new row is its creator's, whoever touched it since
            if not mine(pg, by):
                what = "edited the page" if noun == "page" else ("added" if new else "edited") + f" the {noun} \"{title[:80]}\"{where}"
                hub.event(anchor, {"title": name, "who": uname(pg.get(by)), "url": url, "ts": ed, "text": tag + what}, kind="notion-edit"); n += 1
        st["edited"] = ed
        return n
    def check_row(db, rid, source="push"):
        """A row of a watched database: new comments, and an edit (or its creation) since the database was first seen."""
        st = dbstate(db)
        return scan(f"notion:{db}", rid, st["rows"], rid, base=st["base"], name=f"\"{st['title'][:60]}\"", lead=True, noun="row",
                    tag="(caught up) " if source == "catchup" else "")
    def check_db(db, source="poll"):
        """Rows edited since the last look (the webhook's backstop; comments on unedited rows arrive by push only)."""
        st = dbstate(db); n = 0
        q = api(f"/databases/{db}/query", {"filter": {"timestamp": "last_edited_time", "last_edited_time": {"on_or_after": st["last_iso"]}},
                                            "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}], "page_size": 50})
        for row in q.get("results", []):
            rid = row["id"].replace("-", "")
            if (st["rows"].get(rid) or {}).get("edited") == row["last_edited_time"]: continue
            n += check_row(db, rid, source)
        st["last_iso"] = max([st["last_iso"]] + [row["last_edited_time"] for row in q.get("results", [])])
        return n
    def res(a_id):
        pid = a_id[7:]
        if is_db(pid):
            st = dbstate(pid)
            try: rows = api(f"/databases/{pid}/query", {"sorts": [{"timestamp": "last_edited_time", "direction": "descending"}], "page_size": 25}).get("results", [])
            except Exception: rows = []
            # newest row edit or row creation by a person other than the owner; none → the newest edit at all
            ts = [_ts(r["last_edited_time"]) for r in rows if not mine(r, "last_edited_by")] + [_ts(r["created_time"]) for r in rows if not mine(r, "created_by")]
            ts = ts or [_ts(r["last_edited_time"]) for r in rows[:1]]
            return {"title": f"\"{st['title'][:60]}\"", "url": st["url"] or f"https://www.notion.so/{pid}", "seen": now_iso_at(max(ts)) if ts else None}
        try: pg = api(f"/pages/{pid}")
        except urllib.error.HTTPError as e:
            if e.code not in (400, 403, 404): return {"url": f"https://www.notion.so/{pid}"}       # Notion's trouble, not a refusal: tried again
            return {"title": f"{pid[:8]}…", "url": f"https://www.notion.so/{pid}", "unreadable": "Notion shows the hub's read token no page there (a wrong link, or a page the token's owner cannot open)"}
        except Exception: return {"url": f"https://www.notion.so/{pid}"}
        # newest edit or comment by someone else (an edit by the owner hides who edited before him, so then only comments count)
        self_ok = bool(os.environ.get("ANCHOR_HUB_ALLOW_SELF"))
        ts = [pg.get("last_edited_time")] if self_ok or (pg.get("last_edited_by") or {}).get("id") not in me_ids else []
        try: ts += [c.get("created_time") for c in api(f"/comments?block_id={pid}&page_size=100").get("results", []) if self_ok or (c.get("created_by") or {}).get("id") not in me_ids]
        except Exception: pass
        ts = [_ts(x) for x in ts or [pg.get("last_edited_time")] if x]
        return {"title": f"\"{title_of(pg)[:60]}\"", "url": pg.get("url", f"https://www.notion.so/{pid}"), "seen": now_iso_at(max(ts)) if ts else None}
    hub.resolvers["notion"] = res
    with hub.lock: hub.status["notion"] = {"ready": True, "since": now_iso()}
    log.info("notion: ready (%d own user ids)", len(me_ids))
    state: dict[str, dict] = {}   # page id → {"edited": iso, "comments": set(ids)}
    sv = hub.saved.get("notion") or {}
    for pid, v in (sv.get("pages") or {}).items(): state[pid] = {"edited": v.get("edited"), "comments": set(v.get("comments") or [])}
    for db, v in (sv.get("dbs") or {}).items():
        dbs[db] = {**v, "sources": set(v.get("sources") or []), "rows": {r: {"edited": x.get("edited"), "comments": set(x.get("comments") or [])} for r, x in (v.get("rows") or {}).items()}}
    hub.savers["notion"] = lambda: {"pages": state, "dbs": dbs}
    def catch_up_notion(since: float) -> int:
        """A reboot's resume: every watched page and database from `since`, against the saved state, so nothing already
        queued comes twice. A page with no saved state: its comments and edit after `since` count."""
        with hub.lock: ids = [k[7:] for k in hub.bindings if k.startswith("notion:")]
        n = 0
        for pid in ids:
            try:
                if is_db(pid):
                    st = dbstate(pid); st["base"] = min(st["base"], since)
                    st["last_iso"] = min(st["last_iso"], datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
                    n += check_db(pid, "catchup"); continue
                n += scan(f"notion:{pid}", pid, state, pid, base=since, since=since, tag="(caught up) ", tag_comments=True, skip_trashed=False)
            except Exception as e: log.warning("notion catch-up %s: %s", pid[:8], str(e)[:120])
        return n
    hub.catchups["notion"] = catch_up_notion
    hook_tok = env.get("NOTION_HOOK_TOKEN", "").strip()
    reach: dict[str, bool] = {}   # page id → connection can see it (push-covered) or not (fallback poll)
    def hook_api(path):
        req = urllib.request.Request("https://api.notion.com/v1" + path, headers={"Authorization": f"Bearer {hook_tok}", "Notion-Version": "2022-06-28"})
        with urllib.request.urlopen(req, timeout=20) as r: return json.load(r)
    def reachable(pid):
        if pid in reach: return reach[pid]
        ok = False
        if hook_tok:
            try: hook_api(f"/pages/{pid}"); ok = True
            except Exception:
                try: hook_api(f"/databases/{pid}"); ok = True
                except Exception: ok = False
        reach[pid] = ok
        with hub.lock:
            st = hub.status["anchors"].setdefault(f"notion:{pid}", {}); st["mode"] = "push" if ok else "poll"
        return ok
    def check_page(pid, source="poll"):
        """A watched page: first sight is the baseline; after it, new comments and edits by other people."""
        n = scan(f"notion:{pid}", pid, state, pid, seed_all=True, skip_trashed=False)
        if n and source == "health" and reach.get(pid): hub.push.setdefault("notion", {})["push_miss"] = now_iso()
        return n
    verif = {"token": (watches_load().get("notion") or {}).get("verification_token")}
    def hook_notion(h, body):
        try: data = json.loads(body or b"{}")
        except Exception: return 400, "bad body"
        if "verification_token" in data:      # one-time subscription handshake: the owner pastes this into the Notion UI
            verif["token"] = data["verification_token"]; w = watches_load(); w["notion"] = {"verification_token": verif["token"]}; watches_save(w)
            hub.push.setdefault("notion", {})["verification_token"] = verif["token"]; hub.write_status()
            log.info("notion hook: verification token received — paste it in the subscription form: %s", verif["token"]); return 200, "ok"
        sig = h.get("X-Notion-Signature", "")
        if not verif["token"]: return 401, "not verified yet"
        want = "sha256=" + hmac.new(verif["token"].encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, want): return 401, "bad signature"
        ent = data.get("entity") or {}; pid = (ent.get("id") or "").replace("-", "")
        par = ((data.get("data") or {}).get("parent") or {})
        if ent.get("type") == "comment":   # comment events name the parent page in data.parent
            pid = par.get("id", "").replace("-", "")
        elif ent.get("type") in ("page", "block") and par.get("id"): row_parent[pid] = (par["id"].replace("-", ""), par.get("type", ""))   # a row names its database, a subpage its page
        if pid: hub.triggers.put(("notion", pid))
        hub.push.setdefault("notion", {})["last_event"] = now_iso()
        return 200, "ok"
    hub.hooks["/hook/notion"] = hook_notion
    hub.push.setdefault("notion", {})["mode"] = "push" if hook_tok else "poll (no NOTION_HOOK_TOKEN)"
    timers = {"health": 0.0, "fallback": 0.0}
    def one_pass():
        last_health = timers["health"]; last_fallback = timers["fallback"]
        with hub.lock: ids = [k[7:] for k in hub.bindings if k.startswith("notion:")]
        db_ids = [i for i in ids if is_db(i)]; pages = [i for i in ids if i not in db_ids]
        due: dict[str, str] = {}
        try:
            while True:
                k, pid = hub.triggers.get(timeout=1)
                if k == "notion": due[pid] = "push"
                else: hub.triggers.put((k, pid)); break
        except queue.Empty: pass
        now = time.time()
        health_due = now - last_health >= HEALTH
        if health_due: last_health = timers["health"] = now; due.update({p: "health" for p in ids})
        health_ids = set(ids) if health_due else set()           # the pages the health re-read covers, whatever the poll below calls them
        if int(now // NPOLL) != int(last_fallback // NPOLL):   # once per wall-clock NPOLL slot
            last_fallback = timers["fallback"] = now; due.update({p: "poll" for p in ids if not reachable(p)})
        nerr, nchecked = None, health_due     # a re-read with nothing bound has no call to make, but the beat is stamped (an idle receiver does not age on the board)
        for pid, src in due.items():
            try:
                if pid in pages: check_page(pid, src)
                if pid in db_ids: check_db(pid, src)
                elif src == "push":                      # an event on some page: a row, or a page below a watched one?
                    for kind, anc, row in climb(pid, pages, db_ids):
                        if kind == "db" and row == pid: check_row(anc, pid, src)
                        elif kind == "db": check_child(anc, pid, dbstate(anc)["base"], row=row)
                        else: check_child(anc, pid, t0)
            except Exception as e:
                log.warning("notion %s: %s", pid[:8], str(e)[:160])
                if src == "health" or pid in health_ids: nerr = nerr or f"{pid[:8]}: {str(e)[:60]}"
        if nchecked: hub.health("notion", nerr is None, nerr)       # the 30-min re-read is Notion's real check
        elif due: hub.write_status()
    def loop(): guarded_loop(hub, "notion", one_pass, retry=1.0)    # each pass waits on the trigger queue (a second at most); a pass that raises is logged and the next one runs
    threading.Thread(target=loop, daemon=True).start()
