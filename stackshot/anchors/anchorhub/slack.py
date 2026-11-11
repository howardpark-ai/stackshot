"""anchorhub.slack — Slack (Socket Mode, user token): new messages and edits in watched channels and DMs, with a 30-min catch-up.

The hub's own user (`me`, the owner) is not news: its posts and edits are dropped, except in the channels listed in
[anchor_hub] slack_allow_self_channels (channel ids, a TOML list or one comma- or whitespace-separated string; read at each
message, so a config reload applies it at once), where his own posts and edits are delivered like anyone's. A bot post stays
dropped there too (a bot_id or subtype bot_message): the incoming webhook that posts the briefing would otherwise loop.
ANCHOR_HUB_ALLOW_SELF (env, every receiver) still lets every self post through, everywhere.
The owner's own posts in a digest channel reach the session that reads it.

Every message also carries its whole text (full, newlines kept) and its ids (meta: ts, and thread_ts for a thread reply), which
a direct anchor ([anchor_hub] direct, core.direct()) delivers in full. On a direct anchor every bot's message is dropped, edits
and catch-up included (the session's replies come back through a webhook as a bot post, and letting
one through would loop the chat)."""
import os, re, threading, time
from .core import Hub, HEALTH, _cfg, direct, log, now_iso, now_iso_at, read_env, guarded_loop

WATCH = 60   # s; the socket check and the board's health stamp for Slack (receiver_health.EVERY holds the same beat)

def self_channels() -> set[str]:
    """[anchor_hub] slack_allow_self_channels as a set of channel ids (a list, or a comma- or whitespace-separated string)."""
    v = _cfg.get("anchor_hub", "slack_allow_self_channels") or []
    if isinstance(v, str): v = [v]
    return {c for x in v for c in re.split(r"[\s,]+", str(x)) if c}

def self_ok(cid, m) -> bool:
    """A message by the hub's own user passes: everywhere under ANCHOR_HUB_ALLOW_SELF; in an opted-in channel when it is no
    bot's post (the owner's own posts in a briefing channel reach the session that reads it; the briefing's webhook
    posts there too, and letting a bot through would loop)."""
    if os.environ.get("ANCHOR_HUB_ALLOW_SELF"): return True
    return cid in self_channels() and not m.get("bot_id") and m.get("subtype") != "bot_message"

def is_bot(m) -> bool:
    """A bot's message: a bot_id, or subtype bot_message."""
    return bool(m.get("bot_id")) or m.get("subtype") == "bot_message"

def bot_on_direct(cid, m) -> bool:
    """A bot's message on a direct anchor: dropped, so the session's own replies (a webhook's bot post) never come back."""
    return f"slack:{cid}" in direct() and is_bot(m)

def ids(m, ts=None) -> dict:
    """The message's ids for a direct notice: ts, and thread_ts when it is a reply in a thread (thread_ts set and not its own ts)."""
    ts = m.get("ts") or ts; th = m.get("thread_ts")
    return {"ts": ts, **({"thread_ts": th} if th and th != ts else {})}

def run(hub: Hub):
    from slack_sdk import WebClient
    from slack_sdk.socket_mode import SocketModeClient
    from slack_sdk.socket_mode.request import SocketModeRequest
    from slack_sdk.socket_mode.response import SocketModeResponse
    env = read_env()
    web = WebClient(token=env["SLACK_USER_TOKEN"].strip())
    me = web.auth_test()["user_id"]
    names: dict[str, str] = {}
    gone: set[str] = set()          # channels Slack says the hub's user cannot see
    def chan(cid):
        if cid in gone: gone.discard(cid); names.pop(cid, None)     # asked again by the hub's retry
        if cid not in names:
            try:
                c = web.conversations_info(channel=cid)["channel"]
                if c.get("is_im"): names[cid] = "DM " + user(c["user"])
                elif c.get("is_mpim"):
                    mem = [m for m in web.conversations_members(channel=cid)["members"] if m != me]
                    names[cid] = "Group DM " + ", ".join(user(m).split(" ", 1)[-1] for m in mem)
                else: names[cid] = "#" + c["name"]
            except Exception as e:
                err = getattr(getattr(e, "response", None), "get", lambda k: None)("error")
                if err not in ("channel_not_found", "not_in_channel"): return cid        # Slack's trouble, not a refusal: not kept, tried again
                names[cid] = cid; gone.add(cid)
        return names[cid]
    def seen(cid):
        """Newest post by someone else, by the notices' rule (bots, joins and other subtypes don't count); none → the newest post."""
        try:
            ms = [m for m in web.conversations_history(channel=cid, limit=100)["messages"] if m.get("subtype") in (None, "file_share", "thread_broadcast")]
            m = next((m for m in ms if m.get("user") != me or self_ok(cid, m)), ms[0] if ms else None)
            return now_iso_at(float(m["ts"])) if m else None
        except Exception as e: log.warning("slack seen %s: %s", cid, str(e)[:120]); return None
    def res(a):
        cid = a[6:]; name = chan(cid)
        if cid in gone: return {"title": cid, "url": f"https://{team}.slack.com/archives/{cid}", "unreadable": "Slack shows the hub's user no such channel or conversation"}
        if name == cid: return {"url": f"https://{team}.slack.com/archives/{cid}"}
        return {"title": name, "url": f"https://{team}.slack.com/archives/{cid}", "seen": seen(cid)}
    hub.resolvers["slack"] = res
    team = web.auth_test().get("url", f"https://{_cfg.get('anchor_hub', 'slack_team') or 'app'}.slack.com/").split("//")[1].split(".")[0]
    def user(uid):
        if uid not in names:
            try: u = web.users_info(user=uid)["user"]; names[uid] = u.get("real_name") or u["name"]
            except Exception: names[uid] = uid
        return names[uid]
    hw: dict[str, float] = {k: float(v) for k, v in ((hub.saved.get("slack") or {}).get("hw") or {}).items()}   # channel → newest message ts
    # the socket delivered (restored at start); the catch-up starts after it
    t_start = time.time()
    hub.savers["slack"] = lambda: {"hw": dict(hw)}
    def handle(client: SocketModeClient, req: SocketModeRequest):
        if req.type == "events_api":
            client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
            ev = req.payload.get("event", {})
            if ev.get("type") != "message": return
            cid, sub = ev.get("channel"), ev.get("subtype")
            if cid and sub != "message_changed":
                try: hw[cid] = max(hw.get(cid, 0.0), float(ev.get("ts") or 0))
                except Exception: pass
            def clip(t, n, ts):   # say when a notice is cut, and how to get the rest (a bare "…" would hide a paragraph)
                t = t.replace("\n", " ")
                return t if len(t) <= n else t[:n] + f" [… truncated, {len(t):,} chars — fetch message ts {ts}]"
            if sub == "message_changed":
                # An edit (also how Slack reports a file added to an existing message). Delivered whenever the text differs
                # at all or a file was added; only a byte-identical text (a link unfurl, an attachment change) stays silent
                # (a same-length rewrite can flip the meaning, so no length threshold; the earlier ≥ 40 chars /
                # ≥ 20 % rule is not enough: a post can grow by several paragraphs or a file after delivery.
                new, old = ev.get("message") or {}, ev.get("previous_message") or {}
                if bot_on_direct(cid, new): return
                if new.get("user") == me and not self_ok(cid, new): return     # the edited message itself decides
                if new.get("subtype") == "tombstone": return
                nt, ot = (new.get("text") or ""), (old.get("text") or "")
                nf = [f.get("name") or f.get("id") for f in new.get("files") or []]
                of = [f.get("name") or f.get("id") for f in old.get("files") or []]
                added = [f for f in nf if f not in of]
                if not added and nt == ot: return
                ts = new.get("ts") or ev.get("ts")
                try: url = web.chat_getPermalink(channel=cid, message_ts=ts)["permalink"]
                except Exception: url = f"slack:{cid}/p{ts}"
                delta = f"ts {ts}; {len(ot):,}→{len(nt):,} chars; files {len(of)}→{len(nf)}" + (f", added {', '.join(added)}" if added else "")
                hub.event(f"slack:{cid}", {"title": chan(cid), "who": user(new["user"]) if new.get("user") else (new.get("username") or "bot"),
                                           "text": f"({delta}) " + clip(nt, 300, ts), "url": url, "ts": ts,
                                           "full": nt + (f"\n[files added: {', '.join(added)}]" if added else ""), "meta": ids(new, ts)}, kind="slack-edit")
                return
            if sub not in (None, "file_share", "thread_broadcast"): return
            if bot_on_direct(cid, ev): return
            if ev.get("user") == me and not self_ok(cid, ev): return   # self-suppression, but for the opted-in channels
            ts = ev.get("ts")
            try: url = web.chat_getPermalink(channel=cid, message_ts=ts)["permalink"]
            except Exception: url = f"slack:{cid}/p{ts}"
            files = [f.get("name") or f.get("id") for f in ev.get("files") or []]
            txt = clip(ev.get("text") or "", 140, ts) + (f" [files: {', '.join(files)}]" if files else "")
            hub.event(f"slack:{cid}", {"title": chan(cid), "who": user(ev["user"]) if ev.get("user") else (ev.get("username") or "bot"),
                                       "text": txt, "url": url, "ts": ts,
                                       "full": (ev.get("text") or "") + (f"\n[files: {', '.join(files)}]" if files else ""), "meta": ids(ev)})
    client = SocketModeClient(app_token=env["SLACK_APP_TOKEN"].strip(), web_client=web)
    client.socket_mode_request_listeners.append(handle)
    try: client.connect()
    except Exception:
        # a failed start is retried by start_receiver, which builds a new client: close this one so its two daemon threads do not stay behind
        try: client.close()
        except Exception: pass
        raise
    with hub.lock: hub.status["slack"] = {"connected": True, "user": me, "since": now_iso()}
    log.info("slack: connected as %s", me)
    def catch_up(since: float | None = None):
        """Every HEALTH s, and on a reboot's resume from its pause time: new top-level messages in the watched channels
        that the socket did not deliver (Slack's only backstop; thread replies and edits are the socket's alone). Returns how
        many it caught."""
        with hub.lock: chans = [k[6:] for k in hub.bindings if k.startswith("slack:")]
        chans += [k[6:] for k in direct() if k.startswith("slack:") and k[6:] not in chans]   # a direct anchor bound to no project too
        n = 0
        for cid in chans:
            oldest = max(hw.get(cid, 0.0), since) if since is not None else hw.get(cid, t_start)
            ms = web.conversations_history(channel=cid, oldest=f"{oldest:.6f}", limit=100)["messages"]
            for m in sorted(ms, key=lambda m: float(m["ts"])):
                t = float(m["ts"])
                if t <= oldest: continue
                hw[cid] = max(hw.get(cid, 0.0), t)
                if m.get("subtype") not in (None, "file_share", "thread_broadcast"): continue
                if bot_on_direct(cid, m): continue
                if m.get("user") == me and not self_ok(cid, m): continue
                try: url = web.chat_getPermalink(channel=cid, message_ts=m["ts"])["permalink"]
                except Exception: url = f"slack:{cid}/p{m['ts']}"
                txt = (m.get("text") or "").replace("\n", " ")
                hub.event(f"slack:{cid}", {"title": chan(cid), "who": user(m["user"]) if m.get("user") else (m.get("username") or "bot"),
                                           "text": "(caught up) " + txt[:140] + ("…" if len(txt) > 140 else ""), "url": url, "ts": m["ts"],
                                           "full": m.get("text") or "", "meta": {**ids(m), "caught_up": True}}); n += 1
        return n
    last_catch = [time.time()]
    def watch_pass():
        try: ok = bool(client.is_connected())
        except Exception: ok = False
        with hub.lock: hub.status["slack"]["connected"] = ok
        err = None if ok else "socket not connected"
        if time.time() - last_catch[0] >= HEALTH:
            last_catch[0] = time.time()
            try:
                n = catch_up()
                hub.push.setdefault("slack", {})["last_catchup"] = now_iso()
                if n: hub.push["slack"]["push_miss"] = now_iso(); log.warning("slack: catch-up found %d message(s) the socket did not deliver", n)
            except Exception as e: err = err or f"catch-up failed: {str(e)[:80]}"; log.warning("slack catch-up: %s", str(e)[:160])
        hub.health("slack", ok and err is None, err)
    def watch(): guarded_loop(hub, "slack", watch_pass, every=lambda: WATCH, retry=WATCH, pause_first=True)    # a pass that raises is logged and the next one runs a minute later
    hub.catchups["slack"] = lambda since: catch_up(since)
    threading.Thread(target=watch, daemon=True).start()
