"""anchorhub.gworkspace — Google Drive and Gmail: push channels (Drive changes.watch, Gmail Pub/Sub) with cursor polling behind them."""
import json, os, glob, hmac, queue, threading, time, uuid
from stackshot.anchors import gmail_query as _gq
from .core import Hub, HEALTH, HOOK_URL, WATCHES, _anc, _cfg, _ts, guarded_loop, log, now_iso, now_iso_at, read_env, transient

GDIR = str(_cfg.secrets("anchor-hub", "google"))
ROUTES = ("/hook/drive", "/hook/gmail")   # the webhooks this receiver registers in run(); anchor-hub answers them 503, not 404, while its start is being retried
HISTORY_PAGE = 500    # records asked of Gmail's history.list per call (its largest page)
HISTORY_PAGES = 10    # calls per mailbox per poll: 5000 records; a busier mailbox is read on in the next poll from where this one stopped
MESSAGE_GETS = 200    # messages.get calls per mailbox per poll: a poll that reaches it stops after the last history record it handled whole, and the next poll goes on from there; one record is never split,
                      # so a single record that names more mails than this is read whole in one poll (the cap is checked between records, never inside one)
SENT_KEEP = 1000      # message ids remembered per mailbox as handled (saved with the cursor): the mail a repeated history record names is not delivered twice
GET_TRIES = 3         # messages.get attempts for one mail in all, the first included: a get that fails is tried again at a later poll, and given up on (with a log line) after this many
RETRY_KEEP = 500      # failed gets kept per mailbox (saved with the cursor) for the next polls; past it the oldest is given up on, with a log line
GPOLL = 5   # s; fallback only — used while push for that account is unavailable
def _gmail_poll() -> int: return int(_cfg.get("anchor_hub", "gmail_poll_seconds") or 300)  # s; a mailbox whose watch Google refuses is polled for good (an account with no Pub/Sub topic
                                                                         # to push to), so not at the fallback's pace
def mailbox_labels(emails) -> dict:
    """{label: address} of the mailboxes given by address: a mailbox is named by the label [anchor_hub] gmail_names gives its address
    ({ work = "ada@example.com" }), else by the address itself. A Gmail anchor scopes itself to mailboxes by these names (gmail:q@work:from:x)."""
    cfg = _cfg.get("anchor_hub", "gmail_names") or {}
    given = {str(v).strip().lower(): str(k).strip() for k, v in cfg.items() if _cfg.GMAIL_LABEL.match(str(k).strip()) and _cfg.GMAIL_ADDR.match(str(v).strip())} if isinstance(cfg, dict) else {}   # the entries gmail_names_notes says are skipped
    return dict(sorted((given.get(e.lower(), e), e) for e in emails))      # by name: the anchors service's status file and the server's text agree on the order
def http_status(e) -> int | None:
    """The HTTP status a Google client error carries (googleapiclient's HttpError has it as resp.status, and as status_code in newer releases), else None. Never read from the
    error's text: that holds the request URL, whose history id or page token can spell any number."""
    for v in (getattr(getattr(e, "resp", None), "status", None), getattr(e, "status_code", None), getattr(e, "status", None)):
        try: return int(v)
        except (TypeError, ValueError): continue
    return None
def saved_hist(v) -> str | None:
    """A Gmail history id from the saved state: Gmail's are strings of digits; anything else (a number, an empty string, a list, None) is no position."""
    return v if isinstance(v, str) and v.isascii() and v.isdigit() else None
def saved_page(v) -> str | None:
    """A Drive page token from the saved state: a non-empty string; anything else is no position."""
    return v if isinstance(v, str) and v else None
def saved_sent(v) -> list:
    """The handled mail ids from the saved state, the last SENT_KEEP: a list of strings, else (a dict, a number, None, a list holding anything but strings) none at all."""
    return list(v[-SENT_KEEP:]) if isinstance(v, list) and all(isinstance(x, str) for x in v) else []
def saved_retry(v) -> list:
    """The failed gets from the saved state, [id, thread id, tries so far] each, the last RETRY_KEEP: an entry of any other shape (or one with no tries left) is dropped, the rest kept."""
    if not isinstance(v, list): return []
    ok = [[e[0], e[1], e[2]] for e in v if isinstance(e, list) and len(e) == 3 and isinstance(e[0], str) and e[0] and isinstance(e[1], str) and e[1]
          and isinstance(e[2], int) and not isinstance(e[2], bool) and 0 < e[2] < GET_TRIES]
    return ok[-RETRY_KEEP:]
def query_hits(q_anchors, address: str, hdr: dict, boxes: dict) -> list:
    """The Gmail query anchors (`gmail:q:` and `gmail:q@…:` ids) that a mail with the headers `hdr`, which arrived in the mailbox at `address`, matches: the mailbox must
    be one the anchor reads (all of them when it names none), and its terms must match."""
    out = []
    for qa in q_anchors:
        q = _anc.gmail_query(qa)
        if q is not None and _anc.gmail_reads(qa, address, boxes) and header_match(q[1], hdr): out.append(qa)
    return out
# One lock around every Google API call. google-api-python-client sits on httplib2, which is not
# thread-safe: each account's drive/gmail service shares one connection, and the poll loop, the renewal thread and the
# label resolvers can use it at the same moment during startup — interleaved TLS records can corrupt the connection and even
# crash the process.
# Google calls here are few and light, so serializing them costs nothing.
GAPI = threading.RLock()
HEALTH_RETRY = (2.0, 6.0)   # s: a failed health re-read of one account is tried again after each of these waits before Google is marked down (one dropped connection is not an outage)
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
        saved_all = hub.saved.get("google") if isinstance(hub.saved, dict) else None
        sv = saved_all.get(email) if isinstance(saved_all, dict) else None
        if not isinstance(sv, dict): sv = {}                    # a saved state of another shape is no saved state
        resume = set()                                          # the kinds whose saved cursor this start keeps: the first pass leaves it alone instead of resetting it to now
        if saved_page(sv.get("page")): page = sv["page"]; resume.add("drive")                  # resume from the saved cursor, so a downtime's changes replay
        if hist and saved_hist(sv.get("hist")): hist = sv["hist"]; resume.add("gmail")         # (a Gmail history id older than about a week 404s → resync to now)
        accounts.append({"email": email, "drive": drive, "gmail": gmail if (not gmail_only or email in gmail_only) else None, "page": page, "hist": hist, "sent": saved_sent(sv.get("sent")), "retry": saved_retry(sv.get("retry")),
                         "resume": resume, "parents": {}})
        log.info("google: %s ready (drive cursor %s, gmail history %s)", email, page, hist)
    if not accounts: log.warning("google: no tokens in %s — run anchor-hub-google-auth.py", GDIR); return
    state = {"active": set(), "first": True, "last_health": 0.0, "last_fallback": {"drive": 0.0, "gmail": 0.0}}       # defined before the saver: the saver reads it
    def kept(kind): return state["first"] or kind in state["active"]
    # A cursor is saved while its kind is bound (and, until the first pass has seen what is bound, as loaded): a kind with no anchor stops being read, so its cursor goes stale, and a later start must not resume it.
    hub.savers["google"] = lambda: {a["email"]: {"page": a["page"] if kept("drive") else None, "hist": a["hist"] if kept("gmail") else None, "sent": a["sent"], "retry": a["retry"]} for a in accounts}
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
        return http_status(e) in (400, 403, 404)
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
        q = _anc.gmail_query(a_id)
        if q is not None:      # a query: named by its terms and the mailboxes it reads; a scope naming a mailbox that is gone reads nothing and says so
            bx = boxes(); labels, bad = _anc.gmail_mailboxes(a_id, bx)
            if q[0] is not None and not labels:       # a scope that reads nothing: its names are all gone, or it names none (a hand-made `gmail:q@:`)
                return {"title": _anc.gmail_title(a_id, bx), "url": "",
                        "unreadable": ("no mailbox of that name is read by the anchors service (" + ", ".join(bx) + ")") if bad else "its scope names no mailbox, so it reads nothing"}
            return {"title": _anc.gmail_title(a_id, bx), "url": ""}
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
    def boxes() -> dict:
        """{label: address} of the mailboxes whose mail the anchors service reads (GMAIL_ACCOUNTS names them, or all accounts when it is empty)."""
        return mailbox_labels([a["email"] for a in accounts if a["gmail"] is not None])
    with hub.lock: hub.status["google"] = {"accounts": [a["email"] for a in accounts], "mailboxes": boxes(), "since": now_iso()}

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
        try:
            r = a["drive"].changes().list(pageToken=a["page"], spaces="drive", supportsAllDrives=True, includeItemsFromAllDrives=True, pageSize=100,
                fields="newStartPageToken,nextPageToken,changes(fileId,removed,time,file(name,mimeType,webViewLink,createdTime,modifiedTime,lastModifyingUser(displayName,emailAddress)))").execute()
        except Exception as e:
            if http_status(e) != 404: raise     # as for Gmail: only Google's own 404 says the saved position is gone; any other failure leaves it, and the next poll tries again
            a["page"] = a["drive"].changes().getStartPageToken(supportsAllDrives=True).execute()["startPageToken"]      # a saved page token Google no longer knows → from now
            return
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
        history, token = [], None
        try:
            for _page in range(HISTORY_PAGES):       # history.list is paged: the first page alone loses the mail of a busy mailbox, whose cursor then jumps past it
                r = a["gmail"].users().history().list(userId="me", startHistoryId=a["hist"], historyTypes=["messageAdded"], maxResults=HISTORY_PAGE,
                                                      **({"pageToken": token} if token else {})).execute()
                history += r.get("history", [])
                token = r.get("nextPageToken")
                if not token: break
        except Exception as e:
            if http_status(e) != 404: raise     # only Google's own 404 says the history expired; any other failure leaves the cursor, and the next poll tries again
            a["hist"] = a["gmail"].users().getProfile(userId="me").execute()["historyId"]     # history expired → resync cursor
            return
        with hub.lock: bound = list(hub.bindings)
        bx = boxes()
        readers = [k for k in bound if _anc.gmail_query(k) is not None and _anc.gmail_reads(k, a["email"], bx)]     # the query anchors that read this mailbox: a mail in a mailbox nobody reads costs no get
        keys = set(bound)
        sent = list(a["sent"]); known = set(sent)        # the mail already handled in this mailbox (an inclusive startHistoryId repeats the last record); a mail given up on counts as handled
        seen, gets, stopped, failed = set(), 0, None, []     # failed: the gets of this poll that failed, [mail id, thread id, tries so far], tried again at later polls
        def wanted(tid): return bool(readers) or f"gmail:{tid}" in keys
        def fetch(mid, tid):
            """Get one mail and deliver it to the anchors that read it. False when the get failed: nothing was delivered, and the mail is not marked as handled."""
            try: msg = a["gmail"].users().messages().get(userId="me", id=mid, format="metadata", metadataHeaders=["From", "Subject", "To", "Cc"]).execute()
            except Exception as e: log.warning("gmail %s: get of mail %s failed: %s", a["email"], mid, str(e)[:120]); return False
            sent.append(mid); known.add(mid)
            if "SENT" in msg.get("labelIds", []) or "DRAFT" in msg.get("labelIds", []): return True   # self-suppression
            hdr = {x["name"].lower(): x["value"] for x in msg.get("payload", {}).get("headers", [])}
            url = f"https://mail.google.com/mail/u/0/#all/{tid}"
            summ = {"title": f"\"{hdr.get('subject', '(no subject)')[:60]}\"", "who": hdr.get("from", "?").split("<")[0].strip(' "'),
                    "text": (msg.get("snippet") or "")[:140], "url": url, "ts": msg.get("internalDate")}
            if f"gmail:{tid}" in keys: hub.event(f"gmail:{tid}", summ, kind="gmail")
            for qa in query_hits(readers, a["email"], hdr, bx): hub.event(qa, summ, kind="gmail")
            return True
        def give_up(mid, why):
            log.warning("gmail %s: gave up on mail %s (%s)", a["email"], mid, why)
            sent.append(mid); known.add(mid)       # handled: a repeated history record must not start its tries over
        for mid, tid, tries in a["retry"]:      # the gets that failed at an earlier poll, before any new mail; they count against MESSAGE_GETS
            seen.add(mid)
            if mid in known or not wanted(tid): continue
            gets += 1
            if fetch(mid, tid): continue
            if tries + 1 >= GET_TRIES: give_up(mid, f"{GET_TRIES} gets failed")
            else: failed.append([mid, tid, tries + 1])
        for i, h in enumerate(history):
            todo, fresh = [], set()
            for m in h.get("messagesAdded", []):
                mid = m["message"]["id"]; tid = m["message"]["threadId"]
                if mid in seen or mid in known or mid in fresh: continue      # a mail is handled once: not again after an earlier record, an earlier poll, or twice in one record
                fresh.add(mid)
                todo.append((mid, tid, wanted(tid)))
            need = sum(1 for _m, _t, want in todo if want)
            if gets and gets + need > MESSAGE_GETS: stopped = i; break      # the cap on gets in one poll: the records before this one were handled whole, the rest waits for the next poll
            for mid, tid, want in todo:
                seen.add(mid)
                if not want: continue
                gets += 1
                if not fetch(mid, tid): failed.append([mid, tid, 1])
        if len(failed) > RETRY_KEEP:
            for mid, _tid, _n in failed[:-RETRY_KEEP]: give_up(mid, f"more than {RETRY_KEEP} failed gets waiting")
        a["sent"] = sent[-SENT_KEEP:]
        a["retry"] = failed[-RETRY_KEEP:]
        def last_id(upto):      # the id of the last record before `upto` that has one (Gmail gives every record one)
            return next((x["id"] for x in reversed(history[:upto]) if x.get("id")), None)
        if stopped is not None:     # the get cap: go on from the last record handled whole, and read the rest at once
            a["hist"] = last_id(stopped) or a["hist"]
            hub.triggers.put(("gmail", a["email"]))
        elif token and history:      # more pages than one poll reads: go on from the last record read, and read the rest at once
            a["hist"] = last_id(len(history)) or a["hist"]
            hub.triggers.put(("gmail", a["email"]))
        else: a["hist"] = r.get("historyId", a["hist"])

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

    def renew_pass():
        for a in accounts:
            w = watches.get("drive:" + a["email"], {})
            if hub.push.get("drive", {}).get(a["email"], {}).get("mode") == "push" and w.get("expires", 0) - time.time() < 3600: drive_watch(a)
            w = watches.get("gmail:" + a["email"], {})
            if hub.push.get("gmail", {}).get(a["email"], {}).get("mode") == "push" and w.get("expires", 0) - time.time() < 86400: gmail_watch(a)
        hub.write_status()
    def renewals(): guarded_loop(hub, "google renewals", renew_pass, every=lambda: 300, retry=300)

    def poll_checked(poll, a, kind, health):
        """One account's poll. A health re-read (the 30-min check that decides whether Google shows as down) that fails on the network is tried
        again after each wait in HEALTH_RETRY: the cursor calls are repeatable, and a dropped connection (a broken pipe, an SSL EOF) is gone at the next try.
        An error that waiting does not fix (a refused token, a bug) and the last failure are raised as before."""
        for wait in (HEALTH_RETRY if health else ()):
            try: return poll(a)
            except Exception as e:
                if not transient(e) or hub.stopping.is_set(): raise
                log.warning("google %s %s: %s; health re-read tried again in %s s", a["email"], kind, str(e)[:120], wait)
                if hub.stopping.wait(wait): raise
        return poll(a)

    def one_pass():
        active = state["active"]; last_health = state["last_health"]; last_fallback = state["last_fallback"]
        with hub.lock: kinds = {k.split(":", 1)[0] for k in hub.bindings} & {"drive", "gmail"}
        first = state["first"]
        for kind in kinds - active:                     # source just became bound → cursor from now, then register push; at the start of the process the kinds bound already are not new:
            for a in accounts:                          # a kind with a saved cursor keeps it (what arrived while the service was stopped is read from it), one with none starts from now
                try:
                    if kind == "drive":
                        if not (first and "drive" in a["resume"]): a["page"] = a["drive"].changes().getStartPageToken(supportsAllDrives=True).execute()["startPageToken"]
                        drive_watch(a)
                    if kind == "gmail" and a["gmail"] is not None:
                        if not (first and "gmail" in a["resume"]): a["hist"] = a["gmail"].users().getProfile(userId="me").execute()["historyId"]
                        gmail_watch(a)
                except Exception as e: log.warning("google %s cursor reset %s: %s", a["email"], kind, str(e)[:120])
            try: hub.write_status()
            except Exception as e: log.warning("google status write after binding %s: %s", kind, str(e)[:120])   # a failed write must not leave the kind unbound: the cursors would be reset and the push channels registered again on every pass
        active = state["active"] = kinds
        state["first"] = False                          # a kind bound from here on is new, whatever was saved: its saved cursor is as old as the last time it was read
        due: set[tuple[str, str]] = set()
        try:
            while True: due.add(hub.triggers.get(timeout=1))
        except queue.Empty: pass
        now = time.time()
        health_due = now - last_health >= HEALTH
        if health_due:                                # health poll: same cursor calls; a hit here = the push missed it
            last_health = state["last_health"] = now
            for k in active:
                for a in accounts: due.add((k, a["email"], "health"))
        for k in active:                                # once per wall-clock slot; poll only the accounts whose push is unavailable
            every = _gmail_poll() if k == "gmail" else GPOLL
            if int(now // every) == int(last_fallback[k] // every): continue
            last_fallback[k] = now
            for a in accounts:
                if k == "gmail" and a["gmail"] is None: continue
                if hub.push.get(k, {}).get(a["email"], {}).get("mode") != "push": due.add((k, a["email"]))
        hchecked, herr = health_due and not active, None     # nothing bound: no call to make, but the beat is stamped, so an idle receiver does not age on the board
        for item in due:
            kind, email = item[0], item[1]
            if kind not in active: continue
            a = next((x for x in accounts if x["email"] == email), None)
            if not a: continue
            try:
                before = hub.status["notices"]
                poll_checked(poll_drive if kind == "drive" else poll_gmail, a, kind, len(item) > 2)
                if len(item) > 2 and hub.status["notices"] > before and hub.push.get(kind, {}).get(email, {}).get("mode") == "push":
                    hub.push[kind][email]["push_miss"] = now_iso(); log.warning("%s %s: health poll found events the push did not deliver", kind, email)
            except Exception as e:
                log.warning("google %s %s: %s", email, kind, str(e)[:200])
                if len(item) > 2: herr = herr or f"{kind} {email}: {str(e)[:60]}"
            if len(item) > 2: hchecked = True
        if hchecked: hub.health("google", herr is None, herr)          # the 30-min re-read is Google's real check
    def loop(): guarded_loop(hub, "google", one_pass, retry=1.0)    # each pass waits on the trigger queue (a second at most); a pass that raises is logged and the next one runs
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
    """gmail:q:<terms> against a mail's lower-cased headers: the grammar (terms, AND, OR, parentheses, key:(a OR b)) is stackshot/anchors/gmail_query.py's."""
    return _gq.matches(q, hdr)
