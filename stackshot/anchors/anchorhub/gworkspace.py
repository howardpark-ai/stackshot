"""anchorhub.gworkspace — Google Drive and Gmail: push channels (Drive changes.watch, Gmail Pub/Sub) with cursor polling behind them."""
import json, os, re, glob, hmac, queue, threading, time, uuid
from .core import Hub, HEALTH, HOOK_URL, WATCHES, _cfg, _ts, log, now_iso, now_iso_at, read_env

GDIR = str(_cfg.secrets("anchor-hub", "google"))
ROUTES = ("/hook/drive", "/hook/gmail")   # the webhooks this receiver registers in run(); anchor-hub answers them 503, not 404, while its start is being retried
GPOLL = 5   # s; fallback only — used while push for that account is unavailable
def _gmail_poll() -> int: return int(_cfg.get("anchor_hub", "gmail_poll_seconds") or 300)  # s; a mailbox whose watch Google refuses is polled for good (an account with no Pub/Sub topic
                                                                         # to push to), so not at the fallback's pace
# One lock around every Google API call. google-api-python-client sits on httplib2, which is not
# thread-safe: each account's drive/gmail service shares one connection, and the poll loop, the renewal thread and the
# label resolvers can use it at the same moment during startup — interleaved TLS records can corrupt the connection and even
# crash the process.
# Google calls here are few and light, so serializing them costs nothing.
GAPI = threading.RLock()
def run(hub: Hub):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import HttpRequest
    if not getattr(HttpRequest.execute, "_anchor_hub_locked", False):
        _execute = HttpRequest.execute
        def _locked_execute(self, *args, **kwargs):
            with GAPI: return _execute(self, *args, **kwargs)
        _locked_execute._anchor_hub_locked = True
        HttpRequest.execute = _locked_execute
    accounts = []
    env0 = read_env()
    gmail_only = {x.strip() for x in env0.get("GMAIL_ACCOUNTS", "").split(",") if x.strip()}   # empty = all accounts
    for f in glob.glob(f"{GDIR}/*.json"):
        email = os.path.basename(f)[:-5]
        creds = Credentials.from_authorized_user_file(f)
        if not creds.valid: creds.refresh(Request())
        drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
        page = drive.changes().getStartPageToken(supportsAllDrives=True).execute()["startPageToken"]
        hist = gmail.users().getProfile(userId="me").execute()["historyId"] if (not gmail_only or email in gmail_only) else None
        sv = (hub.saved.get("google") or {}).get(email) or {}
        if sv.get("page"): page = sv["page"]                    # resume from the saved cursor, so a downtime's changes replay
        if hist and sv.get("hist"): hist = sv["hist"]           # (a Gmail history id older than about a week 404s → resync, as before)
        accounts.append({"email": email, "drive": drive, "gmail": gmail if (not gmail_only or email in gmail_only) else None, "page": page, "hist": hist, "parents": {}})
        log.info("google: %s ready (drive cursor %s, gmail history %s)", email, page, hist)
    if not accounts: log.warning("google: no tokens in %s — run anchor-hub-google-auth.py", GDIR); return
    hub.savers["google"] = lambda: {a["email"]: {"page": a["page"], "hist": a["hist"]} for a in accounts}
    def drive_seen(a, fid, f):
        """Newest change by someone else: a folder's newest child (direct children only — Drive cannot query deeper),
        else the file itself, reaching back through its revisions when the owner made the last edit."""
        def other(x): return ((x.get("lastModifyingUser") or {}).get("emailAddress") != a["email"]) or os.environ.get("ANCHOR_HUB_ALLOW_SELF")
        try:
            if f.get("mimeType") == "application/vnd.google-apps.folder":
                xs = a["drive"].files().list(q=f"'{fid}' in parents and trashed = false", orderBy="modifiedTime desc", pageSize=50,
                                             fields="files(modifiedTime,lastModifyingUser(emailAddress))",
                                             supportsAllDrives=True, includeItemsFromAllDrives=True).execute().get("files", [])
            elif other(f): xs = [f]
            else:
                xs = a["drive"].revisions().list(fileId=fid, pageSize=1000, fields="revisions(modifiedTime,lastModifyingUser(emailAddress))").execute().get("revisions", [])[::-1]
            t = next((x["modifiedTime"] for x in xs if other(x)), None) or (xs[0]["modifiedTime"] if xs and f.get("mimeType") == "application/vnd.google-apps.folder" else f.get("modifiedTime"))
            return now_iso_at(_ts(t)) if t else None
        except Exception as e: log.warning("drive seen %s: %s", fid, str(e)[:120]); return None
    def refusal(e):
        """True when Google itself says this account may not have the thing (not found, forbidden, a malformed id), or the
        account has no client for that service; False for anything else (the network, a 5xx, an expired token)."""
        if isinstance(e, AttributeError): return True                       # a["gmail"] is None: Gmail is not read on this account
        return getattr(getattr(e, "resp", None), "status", None) in (400, 403, 404)
    def res_drive(a_id):
        fid = a_id[6:]; refused = True
        for a in accounts:
            try:
                f = a["drive"].files().get(fileId=fid, fields="name,webViewLink,mimeType,modifiedTime,lastModifyingUser(emailAddress)", supportsAllDrives=True).execute()
                a["parents"]["_name_" + fid] = f["name"]
                return {"title": f"\"{f['name']}\"", "url": f.get("webViewLink", ""), "seen": drive_seen(a, fid, f)}
            except Exception as e: refused = refused and refusal(e)
        return {"url": "", **({"unreadable": "none of the hub's Google accounts can open it (" + ", ".join(a["email"] for a in accounts) + "); it has to be shared with one of them"} if refused else {})}
    def res_gmail(a_id):
        if a_id.startswith("gmail:q:"): return {"title": a_id[8:], "url": ""}
        tid = a_id[6:]; refused = True
        for a in accounts:
            try:
                t = a["gmail"].users().threads().get(userId="me", id=tid, format="metadata", metadataHeaders=["Subject"]).execute()
                subj = next((h["value"] for h in t["messages"][0]["payload"]["headers"] if h["name"].lower() == "subject"), "(no subject)")
                ms = [int(m["internalDate"]) for m in t["messages"] if not {"SENT", "DRAFT"} & set(m.get("labelIds", []))]   # newest mail not from the owner
                ms = ms or [int(m["internalDate"]) for m in t["messages"]]
                return {"title": f"\"{subj[:60]}\"", "url": f"https://mail.google.com/mail/u/0/#all/{tid}", "seen": now_iso_at(max(ms) / 1000) if ms else None}
            except Exception as e: refused = refused and refusal(e)
        return {"url": "", **({"unreadable": "the thread is in none of the mailboxes the hub reads (" + ", ".join(a["email"] for a in accounts if a["gmail"]) + ")"} if refused else {})}
    hub.resolvers["drive"], hub.resolvers["gmail"] = res_drive, res_gmail
    with hub.lock: hub.status["google"] = {"accounts": [a["email"] for a in accounts], "since": now_iso()}

    def parents_of(a, fid, depth=0):
        """all ancestor folder ids of a file (cached), so a folder anchor catches changes anywhere below it"""
        if depth > 8: return set()
        if fid in a["parents"]: return a["parents"][fid]
        try: ps = a["drive"].files().get(fileId=fid, fields="parents", supportsAllDrives=True).execute().get("parents", [])
        except Exception: ps = []
        out = set(ps)
        for p in ps: out |= parents_of(a, p, depth + 1)
        a["parents"][fid] = out
        return out

    def poll_drive(a):
        r = a["drive"].changes().list(pageToken=a["page"], spaces="drive", supportsAllDrives=True, includeItemsFromAllDrives=True, pageSize=100,
            fields="newStartPageToken,nextPageToken,changes(fileId,removed,time,file(name,mimeType,webViewLink,createdTime,modifiedTime,lastModifyingUser(displayName,emailAddress)))").execute()
        for c in r.get("changes", []):
            f = c.get("file") or {}
            who = (f.get("lastModifyingUser") or {})
            if who.get("emailAddress") == a["email"] and not os.environ.get("ANCHOR_HUB_ALLOW_SELF"): continue
            fid = c["fileId"]; a["parents"].pop(fid, None)
            targets = {fid} | parents_of(a, fid)
            with hub.lock: hits = [t for t in targets if f"drive:{t}" in hub.bindings]
            for t in hits:
                aname = a["parents"].get("_name_" + t) or folder_name(a, t)
                if t == fid:
                    text = "removed it" if c.get("removed") else "changed it"
                else:
                    # Drive keeps the uploaded file's own modifiedTime, so "added" = created within 10 min of this change
                    added = f.get("createdTime") and abs(_ts(c.get("time")) - _ts(f["createdTime"])) < 600
                    verb = "removed" if c.get("removed") else ("added" if added else "changed")
                    text = f"{verb} \"{f.get('name', fid)}\""
                hub.event(f"drive:{t}", {"title": f"\"{aname}\"", "who": who.get("displayName") or "someone", "text": text,
                                         "url": f.get("webViewLink") or f"https://drive.google.com/open?id={fid}", "ts": c.get("time")}, kind="drive")
        a["page"] = r.get("nextPageToken") or r.get("newStartPageToken") or a["page"]

    def folder_name(a, fid):
        try: n = a["drive"].files().get(fileId=fid, fields="name", supportsAllDrives=True).execute()["name"]
        except Exception: n = fid
        a["parents"]["_name_" + fid] = n
        return n

    def poll_gmail(a):
        if a["gmail"] is None: return
        try:
            r = a["gmail"].users().history().list(userId="me", startHistoryId=a["hist"], historyTypes=["messageAdded"], maxResults=100).execute()
        except Exception as e:
            if "404" in str(e):   # history expired → resync cursor
                a["hist"] = a["gmail"].users().getProfile(userId="me").execute()["historyId"]
            else: raise
            return
        seen = set()
        for h in r.get("history", []):
            for m in h.get("messagesAdded", []):
                mid = m["message"]["id"]; tid = m["message"]["threadId"]
                if mid in seen: continue
                seen.add(mid)
                with hub.lock:
                    q_anchors = [k for k in hub.bindings if k.startswith("gmail:q:")]
                    hit_thread = f"gmail:{tid}" in hub.bindings
                if not hit_thread and not q_anchors: continue
                try: msg = a["gmail"].users().messages().get(userId="me", id=mid, format="metadata", metadataHeaders=["From", "Subject", "To", "Cc"]).execute()
                except Exception: continue
                if "SENT" in msg.get("labelIds", []) or "DRAFT" in msg.get("labelIds", []): continue   # self-suppression
                hdr = {x["name"].lower(): x["value"] for x in msg.get("payload", {}).get("headers", [])}
                url = f"https://mail.google.com/mail/u/0/#all/{tid}"
                summ = {"title": f"\"{hdr.get('subject', '(no subject)')[:60]}\"", "who": hdr.get("from", "?").split("<")[0].strip(' "'),
                        "text": (msg.get("snippet") or "")[:140], "url": url, "ts": msg.get("internalDate")}
                if hit_thread: hub.event(f"gmail:{tid}", summ, kind="gmail")
                for qa in q_anchors:
                    if header_match(qa[8:], hdr): hub.event(qa, summ, kind="gmail")
        a["hist"] = r.get("historyId", a["hist"])

    watches = {}
    try: watches = json.load(open(WATCHES))
    except Exception: pass
    def save_watches(): json.dump(watches, open(WATCHES, "w"), indent=1)

    def drive_watch(a):
        """Register (or renew) the Drive changes channel for this account. Returns True on success."""
        with GAPI: return _drive_watch(a)       # the loop and the renewal thread may both get here; one at a time
    def _drive_watch(a):
        w = watches.get("drive:" + a["email"], {})
        cid, secret = str(uuid.uuid4()), uuid.uuid4().hex
        body = {"id": cid, "type": "web_hook", "address": f"{HOOK_URL}/hook/drive", "token": secret,
                "expiration": str(int((time.time() + 86000) * 1000))}
        try:
            r = a["drive"].changes().watch(pageToken=a["page"], supportsAllDrives=True, includeItemsFromAllDrives=True, body=body).execute()
        except Exception as e:
            log.warning("drive watch %s: %s", a["email"], str(e)[:160]); hub.push.setdefault("drive", {})[a["email"]] = {"mode": "poll", "error": str(e)[:120]}; return False
        if w.get("channel") and w.get("resource"):
            try: a["drive"].channels().stop(body={"id": w["channel"], "resourceId": w["resource"]}).execute()
            except Exception: pass
        watches["drive:" + a["email"]] = {"channel": cid, "resource": r.get("resourceId"), "secret": secret, "expires": int(r.get("expiration", 0)) // 1000}
        save_watches(); hub.push.setdefault("drive", {})[a["email"]] = {"mode": "push", "expires": now_iso_at(watches["drive:" + a["email"]]["expires"])}
        log.info("drive watch %s: channel until %s", a["email"], hub.push["drive"][a["email"]]["expires"]); return True

    def gmail_watch(a):
        with GAPI: return _gmail_watch(a)
    def _gmail_watch(a):
        if a["gmail"] is None: return False
        env = read_env()
        # Gmail accepts only a topic in the Cloud project of the OAuth client the account's token came from, so an account whose
        # client is in another project names its own topic in stackshot.toml; the rest use the hub's default
        topic = str((_cfg.get("anchor_hub", "gmail_topics") or {}).get(a["email"]) or env.get("GMAIL_PUBSUB_TOPIC", "")).strip()
        if not topic: hub.push.setdefault("gmail", {})[a["email"]] = {"mode": "poll", "error": "no GMAIL_PUBSUB_TOPIC"}; return False
        try: r = a["gmail"].users().watch(userId="me", body={"topicName": topic, "labelIds": ["INBOX"]}).execute()
        except Exception as e:
            log.warning("gmail watch %s: %s", a["email"], str(e)[:160]); hub.push.setdefault("gmail", {})[a["email"]] = {"mode": "poll", "error": str(e)[:120]}; return False
        watches["gmail:" + a["email"]] = {"expires": int(r.get("expiration", 0)) // 1000}; save_watches()
        hub.push.setdefault("gmail", {})[a["email"]] = {"mode": "push", "expires": now_iso_at(watches["gmail:" + a["email"]]["expires"])}
        log.info("gmail watch %s: until %s", a["email"], hub.push["gmail"][a["email"]]["expires"]); return True

    def hook_drive(h, body):
        cid, tok, state = h.get("X-Goog-Channel-ID"), h.get("X-Goog-Channel-Token"), h.get("X-Goog-Resource-State")
        for a in accounts:
            w = watches.get("drive:" + a["email"], {})
            if cid and cid == w.get("channel") and tok and hmac.compare_digest(tok, w.get("secret", "")):
                if state != "sync": hub.triggers.put(("drive", a["email"]))
                return 200, "ok"
        return 401, "unknown channel"
    def hook_gmail(h, body):
        # Pub/Sub push: verify the Google-signed OIDC token, then read emailAddress from the message data
        auth = h.get("Authorization", "")
        if not verify_google_oidc(auth[7:] if auth.startswith("Bearer ") else "", f"{HOOK_URL}/hook/gmail"): return 401, "bad token"
        import base64
        try: data = json.loads(base64.b64decode(json.loads(body)["message"]["data"]))
        except Exception: return 400, "bad body"
        for a in accounts:
            if a["email"] == data.get("emailAddress"): hub.triggers.put(("gmail", a["email"])); return 200, f"ok {a['email']}"   # the log names the mailbox
        return 200, f"ignored {data.get('emailAddress')}"
    hub.hooks["/hook/drive"], hub.hooks["/hook/gmail"] = hook_drive, hook_gmail

    def renewals():
        while True:
            for a in accounts:
                w = watches.get("drive:" + a["email"], {})
                if hub.push.get("drive", {}).get(a["email"], {}).get("mode") == "push" and w.get("expires", 0) - time.time() < 3600: drive_watch(a)
                w = watches.get("gmail:" + a["email"], {})
                if hub.push.get("gmail", {}).get(a["email"], {}).get("mode") == "push" and w.get("expires", 0) - time.time() < 86400: gmail_watch(a)
            hub.write_status(); time.sleep(300)

    def loop():
        active: set[str] = set(); last_health = 0.0; last_fallback = {"drive": 0.0, "gmail": 0.0}
        while True:
            with hub.lock: kinds = {k.split(":", 1)[0] for k in hub.bindings} & {"drive", "gmail"}
            for kind in kinds - active:                     # source just became bound → cursor from now, then register push
                for a in accounts:
                    try:
                        if kind == "drive": a["page"] = a["drive"].changes().getStartPageToken(supportsAllDrives=True).execute()["startPageToken"]; drive_watch(a)
                        if kind == "gmail" and a["gmail"] is not None: a["hist"] = a["gmail"].users().getProfile(userId="me").execute()["historyId"]; gmail_watch(a)
                    except Exception as e: log.warning("google %s cursor reset %s: %s", a["email"], kind, str(e)[:120])
                hub.write_status()
            active = kinds
            due: set[tuple[str, str]] = set()
            try:
                while True: due.add(hub.triggers.get(timeout=1))
            except queue.Empty: pass
            now = time.time()
            if now - last_health >= HEALTH:               # health poll: same cursor calls; a hit here = the push missed it
                last_health = now
                for k in active:
                    for a in accounts: due.add((k, a["email"], "health"))
            for k in active:                                # once per wall-clock slot; poll only the accounts whose push is unavailable
                every = _gmail_poll() if k == "gmail" else GPOLL
                if int(now // every) == int(last_fallback[k] // every): continue
                last_fallback[k] = now
                for a in accounts:
                    if k == "gmail" and a["gmail"] is None: continue
                    if hub.push.get(k, {}).get(a["email"], {}).get("mode") != "push": due.add((k, a["email"]))
            hchecked, herr = False, None
            for item in due:
                kind, email = item[0], item[1]
                if kind not in active: continue
                a = next((x for x in accounts if x["email"] == email), None)
                if not a: continue
                try:
                    before = hub.status["notices"]
                    (poll_drive if kind == "drive" else poll_gmail)(a)
                    if len(item) > 2 and hub.status["notices"] > before and hub.push.get(kind, {}).get(email, {}).get("mode") == "push":
                        hub.push[kind][email]["push_miss"] = now_iso(); log.warning("%s %s: health poll found events the push did not deliver", kind, email)
                except Exception as e:
                    log.warning("google %s %s: %s", email, kind, str(e)[:200])
                    if len(item) > 2: herr = herr or f"{kind} {email}: {str(e)[:60]}"
                if len(item) > 2: hchecked = True
            if hchecked: hub.health("google", herr is None, herr)          # the 30-min re-read is Google's real check
    threading.Thread(target=loop, daemon=True).start()
    threading.Thread(target=renewals, daemon=True).start()

_GOOGLE_CERTS = {"at": 0.0, "keys": None}
def verify_google_oidc(token: str, audience: str) -> bool:
    """Pub/Sub push auth: a Google-signed OIDC JWT with our URL as audience."""
    if not token: return False
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as greq
        info = id_token.verify_oauth2_token(token, greq.Request(), audience=audience)
        return info.get("iss") in ("https://accounts.google.com", "accounts.google.com")
    except Exception as e:
        log.warning("gmail hook: oidc verify failed: %s", str(e)[:120]); return False

def header_match(q: str, hdr: dict) -> bool:
    """gmail:q:<terms> — terms are from:<x> to:<x> cc:<x> subject:<x> person:<x> (person = from OR to OR cc).
    A value runs until the next key:, so `subject:anchor test person:sam@x` is two terms; quotes are optional.
    All terms must match (substring, case-insensitive). A bare word with no key matches the subject."""
    terms = re.findall(r'\s*(?:(from|to|cc|subject|person):)?\s*("[^"]*"|[^\s"][^"]*?)(?=\s+(?:from|to|cc|subject|person):|$)', q.strip())
    if not terms: return False
    for k, v in terms:
        v = v.strip().strip('"').lower(); k = k or "subject"
        if not v: continue
        if k == "person":
            if not any(v in hdr.get(h, "").lower() for h in ("from", "to", "cc")): return False
        elif v not in hdr.get(k, "").lower(): return False
    return True
