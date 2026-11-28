"""anchorhub.github — GitHub through the gh CLI: issues and PRs (comments, state, CI), a repo's releases, a repo's notifications (read with a person's token: the one `gh` runs as when it is a person's, else the token in the file `[anchor_hub] notifications_token_file` names, used for that one endpoint; with an App token and no such file they are not read or counted, and each is said unreadable, naming that setting)."""
import json, os, re, stat, subprocess, threading, time
from datetime import datetime, timezone
from .core import Hub, Transient, _anc, _cfg, _events, _merges, _ts, guarded_loop, log, now_iso, now_iso_at
from stackshot.core import ghbudget as _gb   # the host's one hourly ledger of GitHub calls, shared with the stackshot server (a locked file under <state>/github)

GHPOLL = 60   # s; conditional GETs — a 304 does not count against the API budget
FIRST_PASS = 600   # s; how long the first pass after a start may take before the board counts the silence (announced with hub.hold, cleared by the pass's own check)
BACKOFF = 600   # s; the wait after GitHub refuses a read for its rate limit (announced to the board with hub.hold, so it is not shown stale)
COMMIT_DOWNTIME = 600   # s; a pull request last looked at longer ago than this (or never) was missed by the hub: a new head found then is stamped at its committer date, a new head found live at the time it was seen
LIST_OVERLAP = 60   # s; a repo's list of changed issues is asked from this long before the newest change it showed, so a change at the boundary is not missed (an anchor whose saved state already matches the list is not read again for it)
LIST_MAX_AGE = 86400   # s; a repo's list position not brought up to date for longer than this is not trusted: the repo's finished anchors are read in full once, then the list is used again
LIST_PER_PAGE = 100   # issues in a page of the list (GitHub's largest)
LIST_PAGES = 30   # pages one list read may take; more is a change too large to page through: the position is dropped and the finished anchors are read in full once
LATE_MERGE_S = _events.FLOOR_H * 3600   # s; an anchor first read on a pull request that merged this recently still writes the merge line (the event log's own window: older is no news)
LATE_TRIES = 3   # a late merge line that cannot be written is tried again on the next pass this many times in all; then the anchor is seeded without it (each try is a counted read of the issue)
LATE_SKEW = 120   # s; how far ahead of the hub's clock a merge time may be and still be read as now (GitHub's clock against this one); further ahead is a torn time and writes nothing
PR_FIELDS = ("head_ref", "author", "sha", "own_branch", "key", "looked")   # what the CI state of an anchor says about the pull request itself: dropped when GitHub shows no pull request under that number, so nothing stale is carried into a notice
RECHECK_FAST = 600   # s; a pull request number GitHub answered 404 for is asked again this often during its first RECHECK_FAST_FOR seconds (it may be a number that did not exist yet), then once in RECHECK_SLOW
RECHECK_FAST_FOR = 3600   # s
RECHECK_SLOW = 3600   # s; hourly until the number has been missing for RECHECK_SLOW_FOR seconds, then once in RECHECK_DAILY
RECHECK_SLOW_FOR = 86400   # s
RECHECK_DAILY = 86400   # s
PER_ANCHOR_ETAGS = 6  # ETags kept in the saved file per anchor (pull request, check runs of the newest commit, issue: three in use)
CATCHUP_SHARE = 2 / 3   # an anchor not yet read since the first read or a change of login (a catch-up: every read of it is a full, counted 200, no ETag to answer 304) is started only while the hour's ledger, the server's reads included, holds fewer than this share of [github] read_budget: a third of it is always left, for the server's own reads and for the anchors already read (a change in one of them is a counted 200 too). The check is made before each anchor, so a pass can pass the line by what one anchor costs (a handful of reads), never by more
RETRY_AFTER = 3   # a look that failed this many times in a row is no longer tried every pass, when GitHub answered another look in the passes (a failure of everything may be an outage, not the anchor's: those anchors are tried every pass)
RETRY_FIRST = 4 * GHPOLL   # s; the wait after that, doubled by each further failure up to RETRY_MAX: an anchor that cannot be read (a deleted issue GitHub answers 403 or 5xx for) costs a few reads an hour, not 120, and is behind every anchor not tried yet
RETRY_MAX = 3600   # s
GONE = re.compile(r"HTTP(?:/\d(?:\.\d)?)? 4(?:04|10)\b|Not Found|\bGone\b")   # what GitHub answers for a number with nothing under it, for good: 404, or 410 for a deleted issue (the answer to the question, not a failed look)
APP_TOKEN = re.compile(r"Resource not accessible by integration", re.I)   # what GitHub answers an App's installation token for a call only a person's token may make
NOTIF_SETTING = "[anchor_hub] notifications_token_file"   # the setting that names the file holding the token the notifications are read with (a classic personal token with the `notifications` scope and nothing else)
NOTIF_REFUSED_WHY = f"notifications token refused by GitHub; replace the file named by {NOTIF_SETTING}"
NOTIF_REFUSED = re.compile(r"HTTP(?:/\d(?:\.\d)?)? 40[13]\b|Bad credentials", re.I)   # what GitHub answers a token it will not take
NOTIF_WAIT = re.compile(r"rate limit|abuse|secondary", re.I)   # a 403 that is a wait, not a refusal
NOTIF_OFF_WHY = f"notifications are not read: no token is set for them ({NOTIF_SETTING}) and the token the reader runs as is an App's, which GitHub does not answer the notifications for"   # said on a repo's notification anchors while the reader declines to bind them
REFUSED_READ = re.compile(r"HTTP(?:/\d(?:\.\d)?)? 40[13]\b|Bad credentials|Resource not accessible by integration", re.I)   # what GitHub answers a read its token may not make
REFUSED_WHY = "GitHub refuses the reader's token access to it"   # the reason said on an issue, pull request or releases anchor whose read was refused (HTTP 401 or 403 that is no rate limit), with the code after it
WHY_STARTS = ("notifications are not read:", "notifications token refused", REFUSED_WHY, "GitHub shows ")   # how the reasons the poll says on an anchor begin: it takes back only those
NOTIF_TOKEN_MAX = 4096   # bytes of the token file that are read
def refusal_why(e):
    """The reason a read's error says the anchor cannot be read (one line), or "" for an error that is no refusal (a rate limit or abuse wait, the network, GitHub's own error, anything unsaid)."""
    t = str(e)
    if NOTIF_WAIT.search(t) or not REFUSED_READ.search(t): return ""
    return f"{REFUSED_WHY} (HTTP {'401' if re.search(r'HTTP(?:/\d(?:\.\d)?)? 401\b|Bad credentials', t, re.I) else '403'})"
def scrub(text, token): return str(text).replace(token, "***") if token else str(text)      # an error text never carries a token
class TooManyChanges(Exception): """A repo's list of changed issues runs past LIST_PAGES pages."""
def zulu(t: float) -> str: return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")      # GitHub's time form (a `since` parameter, an `updated_at`)
def finished(st) -> bool:
    """A saved state of a closed issue or pull request (merged or not) whose kind is known: what can still happen to it is a late comment or a reopening, and either moves the repo's list of changed issues."""
    return isinstance(st, dict) and st.get("state") == "closed" and "merged" in st
def run(hub: Hub):
    etags: dict[str, str] = {}
    # the ETags survive a restart, so the first pass after one is answered 304 (free) for every anchor that did not change, not a full 200 (counted)
    # for each of them. An ETag is saved only once the pass has finished with the anchor it belongs to (`committed`, filled by settle()): a save in the
    # middle of a read (the clean stop of a restart, the minute's save) never holds an ETag whose answer the saved state has not taken in yet, so a
    # change that arrives meanwhile is a 200 after the restart and is reported. A 304 needs no body: what the answer would have said is in the saved state.
    failed: list[bool] = [False]                            # set when the look at the anchor in hand failed for a reason that is not the anchor's (a refusal, GitHub's error, a network): it is then not counted as read, and a catch-up tries it again
    touched: list[str] = []                                # the conditional paths read for the anchor being looked at
    errs: list[str] = []                                   # the error texts of the failed reads of the anchor itself (an issue or pull request's issue read, a releases read) in the look in hand (the poll thread alone): what says, after the look, that GitHub refused the anchor
    nothing: list[bool] = [False]                          # the anchor's issue read answered "not found" in the look in hand
    committed: dict[str, dict[str, str]] = {}              # anchor id → {path: ETag} as of its last finished look: what is saved
    resolved: dict[str, dict] = {}                         # anchor id → {path, etag, info}: the board's label, answered from here on a 304
    looked: dict[str, float] = {}                          # anchor id → when the poll last finished with it (a finished anchor that is skipped counts). Saved with the ETags and dropped with them when the login changes: an anchor that is not here has not been read under this login, and is what a catch-up still has to do
    # A finished anchor (a closed issue or pull request) is not read one by one. Each pass asks each repo that has one for the issues and pull requests changed since the last pass (one list read,
    # whatever the number of anchors), and reads in full only the finished anchors that list shows changed: a comment, a reopening, a merge. A token that GitHub renews (an App's installation token
    # lasts an hour) makes every ETag useless, and the list is the one read of a repo that does not depend on one. `cursors` is that position, saved with the rest:
    # repo (lower case) → {"since": the `updated_at` of the newest change the list showed, "at": when the hub last had the list answered, "owed": the anchors still to be read in full because the list showed them changed
    # (or, after a fallback, because nothing is known of them since the position was made), "catch": that fallback is under way (its reads are paced like a catch-up's)}. A repo with no position, or one older
    # than LIST_MAX_AGE, gets the fallback: the position is made first (the newest change GitHub shows), then every finished anchor of the repo is read in full once; after that the list is used.
    cursors: dict[str, dict] = {}
    list_tags: dict[str, dict[str, str]] = {}              # repo → the ETag of the list's first page (memory only: a list that answers 304 is the one the position already took in)
    plan: dict[str, dict] = {}                             # repo → this pass's list: {"ok": it was read (or no list is needed), "items": {issue number: what the list showed}}
    pass_ids: dict[str, dict[str, str]] = {}               # repo → {issue number: the bound anchor id}, for the issue and pull request anchors of this pass
    listed = [False]                                       # a list read was answered in this pass
    # GitHub's numeric repository ID (repository.id) survives a transfer to another owner; the anchor's owner/name does not. IDs are learnt from the
    # responses that carry one, by the repo name the anchor uses, and put on every event as repo_id (Event.repo_id, matched by [pilot] own_repos):
    # a notification thread's `repository`, a pull request's `base.repo`, an issue's `repository` when GitHub includes it. A release answer has none
    # (its event gets the ID only once another call on the same repo has seen it); an event with no ID is matched by name, as before.
    repo_ids: dict[str, int] = {}
    archived: dict[str, float] = {}                        # repo (lower case) → when a read first showed it archived (`archived` on the repository object): saved as github_repos, read by the server's anchor sweep (anchors/anchor_sweep.py)
    gone: dict[str, float] = {}                            # anchor id → when the read of an issue or pull request that had been read before first answered "not found" (a deleted repository or issue) AND another read of the same repository has answered since (the token still has access, so the 404 is about this number and not about the token); dropped by the next read that finds it, and by the anchor's leaving the bindings. Saved as github_repos
    suspect: dict[str, float] = {}                         # anchor id → when the read of an anchor that had been read before first answered "not found" (memory only): it becomes `gone` once `repo_ok` shows a later read of the repository that was not a 404
    repo_ok: dict[str, float] = {}                         # repo (lower case) → when a read of an issue or pull request under it last got an answer that was not "not found" (a 304 counts): the token still reaches the repository
    def learn(repo, obj):
        if isinstance(obj, dict) and isinstance(obj.get("id"), int) and not isinstance(obj.get("id"), bool) and obj["id"] > 0: repo_ids[repo.lower()] = obj["id"]
        if isinstance(obj, dict) and isinstance(obj.get("archived"), bool): archived.setdefault(repo.lower(), time.time()) if obj["archived"] else archived.pop(repo.lower(), None)
    def rid(repo): return repo_ids.get(repo.lower(), 0)
    def held():
        """Seconds until the hourly read cap has room (0 = it has): the cap is the ledger's, shared with the server (ghbudget.py, [github] read_budget)."""
        return _gb.wait(_gb.READ, _gb.read_cap())
    def paced():
        """Seconds until a catch-up may start another anchor (0 = it may): the ledger's count of the hour, the server's reads included, against CATCHUP_SHARE of the cap. Not the cap itself, so this wait is no failure."""
        return _gb.wait(_gb.READ, max(1, int(_gb.read_cap() * CATCHUP_SHARE)))
    def counted(r):
        """A `gh` call GitHub answered goes into the ledger; a call that never reached it (no network) does not."""
        if r.returncode == 0 or not re.search(r"error connecting|could not resolve|timed? ?out|connection (refused|reset)", r.stderr or "", re.I): _gb.note(_gb.READ, caller="receivers")
    def gh(path, conditional=False, capped=True, tags=None, token=None):
        """`tags`: the ETags this read sends and updates (the poll's `etags` unless a caller keeps its own). `token`: read with this token instead of the one `gh` holds (it goes to the child's environment as GH_TOKEN,
        never to its arguments, and is struck from any error text)."""
        if capped and (w := held()) > 0: raise RuntimeError(f"the hourly cap on GitHub reads is spent; reads resume in {_gb.held_words(w)}")
        tags = etags if tags is None else tags
        args = ["gh", "api", "-i", path] if conditional else ["gh", "api", path]
        if conditional and tags is etags: touched.append(path)
        if conditional and path in tags: args += ["-H", f"If-None-Match: {tags[path]}"]
        r = subprocess.run(args, capture_output=True, text=True, timeout=30, **({"env": {**os.environ, "GH_TOKEN": token}} if token else {}))
        if conditional:
            head, _, body = r.stdout.partition("\n\n")
            if head.startswith("HTTP/") and " 304" in head.split("\n")[0]: return None        # unchanged, free: not in the ledger
            counted(r)
            for line in head.split("\n"):
                if line.lower().startswith("etag:"): tags[path] = line.split(":", 1)[1].strip()
            if r.returncode: raise RuntimeError(scrub((r.stderr or head).strip(), token)[:120])
            return json.loads(body)
        counted(r)
        if r.returncode: raise RuntimeError(scrub(r.stderr.strip(), token)[:120])
        return json.loads(r.stdout)
    def start_check():
        """The start check → (the login whose own activity is not news, whether the token is a GitHub App's). `gh api /user` answers for a person's login. An App's installation token
        (the bot a server box's `gh` runs as) is answered 403 "Resource not accessible by integration" there and for the notifications, though it reads repositories and pull requests
        fine; `gh api /rate_limit` answers for any token that is accepted, so a 403 of that kind on /user is followed by a probe of /rate_limit and a token that passes it is usable.
        The App's own login cannot be read cheaply (`gh api /app` takes a JWT, not the installation token), so it is the `[anchor_hub] github_login` setting; unset, there is no login, the
        self-activity filter is off (every event, the bot's own included, is news) and one log line says so. Every failure here is raised as a Transient: start_receiver tries the start again
        (5 s doubling to 5 min) until it passes, whatever the cause, a network that is down and a login that is not made yet alike, so a receiver is never left off until the next restart."""
        def failed(e):
            if isinstance(e, subprocess.TimeoutExpired): return Transient("gh api timed out")
            # gh says "error connecting to api.github.com" when the network is down (DNS down at boot): the network's own words; anything else (HTTP 401, not logged in, no gh) is the credential, retried the same way
            return Transient(str(e).replace("\n", " ")[:120] if re.search(r"error connecting|githubstatus|could not resolve|timed? ?out|connection (refused|reset)|HTTP 5\d\d", str(e), re.I)
                             else "gh not authenticated (%s)" % str(e).replace("\n", " ")[:80])
        try: return gh("/user", capped=False)["login"], False      # counted, never held: a spent cap must not read as "gh not authenticated" and turn the receiver off
        except Exception as e:
            if not APP_TOKEN.search(str(e)): raise failed(e)
        try: gh("/rate_limit", capped=False)
        except Exception as e: raise failed(e)
        return str(_cfg.get("anchor_hub", "github_login") or "").strip(), True
    me, app_token = start_check()
    def notfound_why(): return f"GitHub shows {me or 'this token'} no issue or pull request there"
    def read_why(e):
        """Why a read that failed with `e` leaves an issue or pull request anchor unreadable (one line), "" when the failure says nothing of the anchor (a rate limit, the network, GitHub's own error): a 404 or 410 is that nothing is there for this token, a 401 or a 403 that is no rate limit is a refusal."""
        return notfound_why() if GONE.search(str(e)) else refusal_why(e)
    # The notifications are the one read the App token cannot make. `[anchor_hub] notifications_token_file` names a file with a classic personal token that has the `notifications` scope and nothing else; it is
    # used for that endpoint alone, every other read keeps the token `gh` holds. The file is looked at on every use (its size, time and mode are the cache's key), so a replaced file is taken up without a restart.
    # It counts only when it is a regular file, readable by its owner alone (mode 600 or stricter), holding one word. Unset: a person's token reads the notification anchors as before; an App token cannot, so they are not read and each says so on its status (NOTIF_OFF_WHY).
    # Set but not usable, or refused by GitHub (401, or a 403 that is no rate limit): the notification anchors are not read, and their status says why (never the token); a refused token is not asked again
    # until the file changes.
    tok_cache: dict = {"sig": None, "token": None, "why": ""}
    notif_refused: dict = {"sig": None}                    # the signature of the file whose token GitHub refused
    notif_said: list = [None]                              # the standing last logged (a log line per change, not per pass)
    def notif_access():
        """The notifications token's standing now → (state, token, why, signature of the file): "off" (no setting: as before), "ok" (the token to read with), "bad" (the reason, which never holds the token)."""
        raw = str(_cfg.get("anchor_hub", "notifications_token_file") or "").strip()
        if not raw: return "off", None, "", None
        path = os.path.expanduser(raw)
        def bad(why, sig=None): return "bad", None, f"notifications are not read: {NOTIF_SETTING} {why}", sig
        try: st = os.stat(path)
        except OSError: return bad("names a file that does not exist or cannot be read")
        sig = (path, st.st_mode, st.st_size, st.st_mtime_ns, st.st_ino)
        if tok_cache["sig"] != sig:
            tok_cache.update(sig=sig, token=None, why="")
            if not stat.S_ISREG(st.st_mode): tok_cache["why"] = "does not name a regular file"
            elif st.st_mode & 0o177: tok_cache["why"] = "names a file that others can read or write (it must be mode 600)"
            elif st.st_size == 0: tok_cache["why"] = "names an empty file"
            elif st.st_size > NOTIF_TOKEN_MAX: tok_cache["why"] = "names a file that is too large for a token"
            else:
                try:
                    with open(path, "r", encoding="utf-8") as f: word = f.read(NOTIF_TOKEN_MAX).strip()
                except (OSError, UnicodeDecodeError): tok_cache["why"] = "names a file that cannot be read"
                else:
                    if not word: tok_cache["why"] = "names an empty file"
                    elif re.search(r"\s", word): tok_cache["why"] = "names a file that holds more than a single token"
                    else: tok_cache["token"] = word
        if not tok_cache["token"]: return bad(tok_cache["why"], sig)
        if notif_refused["sig"] == sig: return "bad", None, NOTIF_REFUSED_WHY, sig
        return "ok", tok_cache["token"], "", sig
    def flag(a_id, why):
        """Say in an anchor's status that it is not read (`why`: one line), or (why None) take it back when it says one of the two reasons above (the rescan writes the same words when it names the anchor)."""
        with hub.lock:
            sts = hub.status.setdefault("anchors", {})
            if why:
                st = sts.setdefault(a_id, {"last": None}); u = st.get("unreadable")
                if not u: st["unreadable"] = {"since": now_iso(), "first": time.time(), "tries": 1, "why": why, "next": time.time() + 60}
                else: u["why"] = why      # still unreadable, now for another reason: one stretch of time, its removal clock and its warning stand
                return
            st = sts.get(a_id) or {}; u = st.get("unreadable")
            if u and str(u.get("why") or "").startswith(WHY_STARTS):
                if u.get("warned"): u["next"] = 0      # the keeper was told: the next rescan reads it again and says it can be read
                else: del st["unreadable"]
    def notif_anchors():
        with hub.lock: return [k for k in hub.bindings if k.startswith("github:") and k.endswith("@notifications")]
    def refusal(e, token): return bool(token) and bool(NOTIF_REFUSED.search(str(e))) and not NOTIF_WAIT.search(str(e))
    def note_refusal(sig):
        """GitHub refused the notifications token: no read of them until the file changes, said on each notification anchor."""
        notif_refused["sig"] = sig; log.warning("github: GitHub refused the notifications token; the notification anchors are not read until the file named by %s changes", NOTIF_SETTING)
        for k in notif_anchors(): flag(k, NOTIF_REFUSED_WHY)
    def split(a_id): repo, n = a_id[7:].rsplit("#", 1); return repo, n
    def html_of(api_url):
        """An API URL of an issue or PR → its github.com page."""
        return (api_url or "").replace("https://api.github.com/repos/", "https://github.com/").replace("/pulls/", "/pull/")
    def cached_get(a_id, path, token=None):
        """the resolver's read of `path` is conditional on the ETag saved with the last resolution of this anchor → (answer, ETag); an
        answer of None is a 304 (free): the saved resolution stands. The resolver's ETags are its own, apart from the poll's: a 200 here must not
        make the poll's next read of the same issue a 304 it never took in."""
        ent = resolved.get(a_id)
        tags = {path: ent["etag"]} if ent and ent.get("path") == path and ent.get("etag") else {}
        return gh(path, conditional=True, tags=tags, token=token), tags.get(path)
    def keep(a_id, path, tag, info):
        if tag: resolved[a_id] = {"path": path, "etag": tag, "info": info}
        return info
    def res(a_id):
        ent = resolved.get(a_id); cached = dict(ent["info"]) if ent and isinstance(ent.get("info"), dict) else None
        if a_id.endswith("@notifications"):
            repo = a_id[7:-14]
            nstate, ntok, nwhy, nsig = notif_access()
            named = {"title": f"{repo.split('/')[1]} notifications", "url": f"https://github.com/notifications?query=repo%3A{repo.replace('/', '%2F')}", "seen": None}
            if nstate == "bad": return {**named, "unreadable": nwhy}
            if app_token and nstate == "off": return {**named, "unreadable": NOTIF_OFF_WHY}      # an App token cannot read them (the call is a 403) and no token of their own is set: not asked, and said on the anchor
            path = f"/repos/{repo}/notifications?all=true&per_page=50"
            try: ns, tag = cached_get(a_id, path, ntok)
            except Exception as e:
                if refusal(e, ntok): note_refusal(nsig); return {**named, "unreadable": NOTIF_REFUSED_WHY}
                ns, tag = [], None
            if ns is None and cached: return cached                      # 304: as last time
            ts = [_ts(x.get("updated_at")) for x in ns or [] if x.get("updated_at")]
            return keep(a_id, path, tag, {"title": f"{repo.split('/')[1]} notifications", "url": f"https://github.com/notifications?query=repo%3A{repo.replace('/', '%2F')}",
                                          "seen": now_iso_at(max(ts)) if ts else None})
        if a_id.endswith("@releases"):
            repo = a_id[7:-9]; path = f"/repos/{repo}/releases/latest"
            try: rl, tag = cached_get(a_id, path)
            except Exception as e:
                if refusal_why(e): return {"title": f"{repo.split('/')[1]} releases", "url": f"https://github.com/{repo}/releases", "unreadable": refusal_why(e)}
                rl, tag = {}, None
            if rl is None and cached: return cached
            pub = (rl or {}).get("published_at")
            return keep(a_id, path, tag, {"title": f"{repo.split('/')[1]} releases", "url": f"https://github.com/{repo}/releases", "seen": now_iso_at(_ts(pub)) if pub else None})
        repo, n = split(a_id)
        with hub.lock: said = bool(((hub.status.get("anchors") or {}).get(a_id) or {}).get("unreadable"))
        if cached and not said and (state.get(_anc.anchor_id(a_id) or a_id) or {}).get("state") == "closed": return cached      # a finished anchor is not asked again at start-up (one that is said unreadable is: it is read for real); the poll drops this when it sees it change
        path = f"/repos/{repo}/issues/{n}"
        try: i, tag = cached_get(a_id, path)
        except Exception as e:
            why = read_why(e)
            if not why: return {"url": f"https://github.com/{repo}/issues/{n}"}    # not a refusal: tried again
            resolved.pop(a_id, None)
            return {"title": f"{repo}#{n}", "url": f"https://github.com/{repo}/issues/{n}", "unreadable": why}
        if i is None and cached: return cached                           # 304: nothing changed since the last resolution, which is saved
        if i is None: i, tag = gh(path), None                            # a 304 with nothing saved to answer it from cannot happen (no validator was sent); read in full if it does
        learn(repo, i.get("repository"))
        # newest activity by someone else: opened by them, their newest comment, or a close/merge (notified whoever did it)
        self_ok = bool(os.environ.get("ANCHOR_HUB_ALLOW_SELF"))
        ts = [i.get("closed_at")] + ([i.get("created_at")] if self_ok or i["user"]["login"] != me else [])
        whole = True
        if i.get("comments"):
            try: ts += [c["created_at"] for c in gh(f"/repos/{repo}/issues/{n}/comments?per_page=100&page={(i['comments'] - 1) // 100 + 1}") if self_ok or c["user"]["login"] != me]
            except Exception: whole = False
        ts = [_ts(x) for x in ts if x] or [_ts(i.get("updated_at"))]
        info = {"title": f"{repo.split('/')[1]}#{n} \"{i['title'][:50]}\"", "url": i["html_url"], "seen": now_iso_at(max(ts)) if ts else None}
        return keep(a_id, path, tag, info) if whole else info             # an answer the comments read failed in is not saved: it is made again next time
    state: dict[str, dict] = {}
    sv = hub.saved.get("github") or {}
    for k, v in (sv.get("state") or {}).items():
        if isinstance(v, dict) and isinstance(v.get("seen"), list): v["seen"] = set(v["seen"])
        state[_anc.anchor_id(k) or k] = v                     # no silent re-seed after a restart — a downtime's changes are reported; keyed by the anchor's current name ([github.moved])
    ci_st: dict[str, dict] = {_anc.anchor_id(k) or k: {**v, "key": (v["key"][0], tuple(v["key"][1])) if isinstance(v.get("key"), list) else v.get("key")}
                              for k, v in ((hub.saved.get("github") or {}).get("ci") or {}).items()}
    for v in ci_st.values():
        if v.get("pr") is False:                           # saved while no pull request was known under that number: what it says about one (carried over from an entry of another repository's name, or left by an earlier version) is dropped
            for f in PR_FIELDS: v.pop(f, None)
    canon_memo: dict[str, str] = {}; canon_for: list = [None]      # id → its current name, and the [github.moved] table that memo was made under (the poll thread alone uses them)
    def adopt(d, a_id):
        """[github.moved]: saved state, CI state and the like are keyed by the anchor id. When a pair is added while the hub runs (a config reload), the
        entry stored under the other name of the same repository is moved to the id the bindings use now, before it is read, so a run in flight, a
        comment or a merge in the gap is still reported and no entry is left under the dead name. An empty table: nothing is looked at, nothing moves."""
        moved = _cfg.moved_repos()
        if not moved: return
        if moved != canon_for[0]: canon_memo.clear(); canon_for[0] = moved      # a name's current form changes only with the table: remembered until it does
        elif len(canon_memo) > 20000: canon_memo.clear()
        def canon(k):
            c = canon_memo.get(k)
            if c is None: c = canon_memo[k] = _anc.anchor_id(k) or k
            return c
        want = canon(a_id)
        for k in [k for k in d if k != a_id and k.startswith("github:") and canon(k) == want]:
            v = d.pop(k)
            if a_id not in d: d[a_id] = v
    # restore what a 304 needs to be believed — the ETags with the state they were taken at, the learnt repository IDs, the saved
    # resolutions. Another login's ETags are dropped; so is anything that does not read as expected (a file from before this, or a damaged one).
    if sv.get("me") == me:
        try:
            for a, per in (sv.get("etags") or {}).items():
                a = _anc.anchor_id(a) or a
                # an anchor's ETags are kept only with the state they were taken at: no seeded state (and, for an issue or pull request, no CI state) → its first look is a full read that seeds, never a 304 that hides a change
                if a not in state or not (a.endswith("@releases") or a.endswith("@notifications") or a in ci_st): continue
                if isinstance(per, dict) and all(isinstance(p, str) and isinstance(t, str) and t for p, t in per.items()):
                    committed[a] = dict(per); etags.update(per)
            for a, t in (sv.get("looked") or {}).items():
                if isinstance(t, (int, float)) and not isinstance(t, bool) and t >= 0: looked[_anc.anchor_id(a) or a] = float(t)
            for a in committed: looked.setdefault(a, 0.0)      # a file from before `looked` was kept: an anchor with ETags was read, whenever
            for a, ent in (sv.get("resolved") or {}).items():
                if isinstance(ent, dict) and isinstance(ent.get("info"), dict) and isinstance(ent.get("etag"), str) and isinstance(ent.get("path"), str): resolved[_anc.anchor_id(a) or a] = ent
            for k, v in (sv.get("repo_ids") or {}).items():
                if isinstance(v, int) and not isinstance(v, bool) and v > 0: repo_ids[str(k).lower()] = v
        except Exception as e:
            log.warning("github: saved ETags not used (%s)", str(e)[:80]); committed.clear(); etags.clear(); resolved.clear(); looked.clear()
    # the repos' list positions do not depend on the login (the saved state they go with is kept for any login): an entry that does not read as expected is dropped, and its repo gets the fallback
    try:
        for r, ent in (sv.get("lists") or {}).items():
            ow = ent.get("owed", []) if isinstance(ent, dict) else None
            if (isinstance(ow, list) and all(isinstance(x, str) for x in ow) and isinstance(ent.get("since"), str) and _ts(ent["since"]) > 0
                    and isinstance(ent.get("at"), (int, float)) and not isinstance(ent.get("at"), bool) and ent["at"] >= 0):
                cursors[str(r).lower()] = {"since": ent["since"], "at": float(ent["at"]), "owed": {_anc.anchor_id(x) or x for x in ow}, "catch": bool(ent.get("catch"))}
    except Exception as e:
        log.warning("github: saved list positions not used (%s)", str(e)[:80]); cursors.clear()
    def settle(a_id):
        """The look at `a_id` is finished: the ETags it read (and still holds: a read that failed after its 200 dropped its ETag) are what is saved for it."""
        per = committed.setdefault(a_id, {})
        for p in dict.fromkeys(touched):
            if p in etags: per.pop(p, None); per[p] = etags[p]
        while len(per) > PER_ANCHOR_ETAGS: per.pop(next(iter(per)))
        touched.clear()
    def snapshot():
        """The saved read position (each list() / dict() below is one step under the GIL, the poll thread goes on meanwhile). Only watched anchors keep ETags and resolutions."""
        with hub.lock: bound = {_anc.anchor_id(k) or k for k in hub.bindings if k.startswith("github:")}
        return {"state": state, "ci": ci_st, "me": me, "repo_ids": dict(repo_ids),
                "lists": {r: {"since": e["since"], "at": e["at"], "owed": sorted(e["owed"]), "catch": e["catch"]} for r, e in list(cursors.items())},
                "looked": {a: t for a, t in list(looked.items()) if (_anc.anchor_id(a) or a) in bound},
                "etags": {a: dict(per) for a, per in list(committed.items()) if (_anc.anchor_id(a) or a) in bound and per},
                "resolved": {a: dict(e) for a, e in list(resolved.items()) if (_anc.anchor_id(a) or a) in bound}}
    hub.savers["github"] = snapshot
    for k, t in ((hub.saved.get("github_repos") or {}).get("archived") or {}).items():      # what the server's anchor sweep reads of a repository: kept across a restart, and a login change does not drop it
        if isinstance(t, (int, float)) and not isinstance(t, bool) and t > 0: archived[str(k).lower()] = float(t)
    for k, t in ((hub.saved.get("github_repos") or {}).get("gone") or {}).items():
        if isinstance(t, (int, float)) and not isinstance(t, bool) and t > 0: gone[_anc.anchor_id(k) or k] = float(t)
    def repos_record():
        """What the anchor sweep reads of the repositories (github_repos). A mark is kept only while an anchor of its repository is bound: the marks of a repository nothing watches any more are forgotten (an archived repository
        or a gone number that gets an anchor again is learned afresh by a read, never taken from an old mark), and a suspected anchor is promoted to `gone` only when a read of its repository that was not a 404 came at or after its first 404."""
        with hub.lock: bound = {_anc.anchor_id(k) or k for k in hub.bindings if k.startswith("github:")}
        repos = {re.split(r"[#@]", a[7:], maxsplit=1)[0].lower() for a in bound}
        for r in [r for r in list(archived) if r not in repos]: archived.pop(r, None)
        for d in (gone, suspect):
            for a in [a for a in list(d) if a not in bound]: d.pop(a, None)
        for a, t in list(suspect.items()):
            if a in state and "#" in a and repo_ok.get(split(a)[0].lower(), 0.0) >= t: gone.setdefault(a, t)
        return {"archived": dict(archived), "gone": {a: t for a, t in list(gone.items()) if a in state}}
    hub.savers["github_repos"] = repos_record
    hub.resolvers["github"] = res                          # last: the resolver reads `state` and the saved resolutions, which are restored above
    with hub.lock: hub.status["github"] = {"user": me, "since": now_iso()}; hub.push["github"] = {"mode": f"poll · {GHPOLL // 60} min"}
    if not app_token: log.info("github: ready as %s", me)
    elif me: log.info("github: ready with an App token (GET /user is refused to it), as %s: that login's own activity is not news", me)
    else: log.info("github: ready with an App token (GET /user is refused to it) and no [anchor_hub] github_login: the token's own activity is not told apart, so every event is news")
    def release(a_id):
        """Latest published release (drafts and prereleases excluded by the endpoint). The first observation
        seeds silently; a changed tag_name is one notice. A repo with no release yet (404) is seeded as none."""
        repo = a_id[7:-9]
        try: r = gh(f"/repos/{repo}/releases/latest", conditional=True)
        except Exception as e:
            if "404" in str(e) or "Not Found" in str(e): state.setdefault(a_id, {"tag": None}); return
            log.warning("github %s: %s", a_id, str(e)[:120]); failed[0] = True; errs.append(str(e))
            if "rate limit" in str(e).lower() or "403" in str(e): hub.hold("github", BACKOFF); time.sleep(BACKOFF)
            return
        if r is None: return                                  # 304: unchanged
        st = state.get(a_id)
        state[a_id] = {"tag": r["tag_name"]}
        if st is None: log.info("github %s: seeded at %s", a_id, r["tag_name"]); return
        if r["tag_name"] == st["tag"]: return
        pub = now_iso_at(_ts(r.get("published_at")))[:16] if r.get("published_at") else "?"
        hub.event(a_id, {"title": f"{repo.split('/')[1]} releases", "who": f"new release {r['tag_name']}",
                         "text": f"(published {pub} {_cfg.tz_abbr()})", "url": r["html_url"], "ts": r.get("published_at"),
                         "body": (r.get("body") or "") + " " + (r.get("name") or ""), "repo_id": rid(repo)}, kind="github-release")
    REASON = {"author": "on your thread", "comment": "new comment", "mention": "mentioned you", "team_mention": "mentioned your team",
              "review_requested": "review requested", "state_change": "state changed", "ci_activity": "CI", "assign": "assigned to you",
              "subscribed": "update", "manual": "update", "security_alert": "security alert", "invitation": "invitation"}
    def thread_news(repo, n, is_pr, since):
        """What happened on an issue/PR since `since`, from other people: comments, reviews, review comments, and a merge or
        close by anyone. The owner's own pushes, force-pushes, edits and labels are not news (a push to a pull request is not reported as "on your thread" twice). → (text, who, link, etype, board ids the body of a merged pull request names, the kinds whose author_association is the repository's own side, the newest created_at / submitted_at among the items that side wrote or "") or None; etype names each kind of news (core.GH_TYPES),
        joined with "+", for the hub's decision by type (the turn rule's third build)."""
        self_ok = bool(os.environ.get("ANCHOR_HUB_ALLOW_SELF")); t0 = _ts(since) if since else 0
        i = gh(f"/repos/{repo}/issues/{n}")
        news, who, link, types = [], [], i.get("html_url") or f"https://github.com/{repo}/issues/{n}", []
        merged = (i.get("pull_request") or {}).get("merged_at")
        if merged and _ts(merged) > t0: news.append("merged"); who.append(((i.get("closed_by") or {}).get("login")) or ""); types.append("pr_merged")
        elif i.get("closed_at") and i.get("state") == "closed" and _ts(i["closed_at"]) > t0:
            news.append("closed"); who.append(((i.get("closed_by") or {}).get("login")) or ""); types.append("pr_closed" if i.get("pull_request") else "issue_closed")
        def others(xs, stamp):      # other people only: not the owner, not bots (a CI bot's comment is not a person's activity)
            return [x for x in xs or [] if _ts(x.get(stamp)) > t0 and (self_ok or (x.get("user") or {}).get("login") != me)
                    and (x.get("user") or {}).get("type") != "Bot" and not str((x.get("user") or {}).get("login", "")).endswith("[bot]")]
        q = f"since={since}&" if since else ""
        own = lambda xs: any(_events.trusted_association(x.get("author_association")) for x in xs)      # the repository's own side (OWNER, MEMBER, COLLABORATOR) among them, from the payload: a stranger's comment is news for the notice but no activity of the item
        vouched, rv, rc = [], [], []
        said = gh(f"/repos/{repo}/issues/{n}/comments?{q}per_page=50")
        if is_pr:      # a verdict is mostly the owner's or a bot's own comment, which `others` leaves out
            for c in said or []:
                if _ts(c.get("created_at")) > t0: verdict_seen(f"github:{repo}#{n}", repo, f"{repo.split('/')[1]}#{n}", c)
        cs = others(said, "created_at")
        if cs: news.append(f"{len(cs)} new comment" + ("s" if len(cs) > 1 else "")); who += [c["user"]["login"] for c in cs]; link = cs[-1].get("html_url") or link; types.append("comment"); vouched += ["comment"] if own(cs) else []
        if is_pr:
            rv = [r for r in others(gh(f"/repos/{repo}/pulls/{n}/reviews?per_page=100"), "submitted_at") if r.get("state") != "PENDING"]
            if rv: news.append("review " + ", ".join(sorted({r.get("state", "").lower().replace("_", " ") for r in rv}))); who += [r["user"]["login"] for r in rv]; link = rv[-1].get("html_url") or link; types.append("review")
            rc = others(gh(f"/repos/{repo}/pulls/{n}/comments?{q}per_page=50"), "created_at")
            if rc: news.append(f"{len(rc)} review comment" + ("s" if len(rc) > 1 else "")); who += [c["user"]["login"] for c in rc]; link = rc[-1].get("html_url") or link; types.append("review_comment")
            if rv and own(rv) or rc and own(rc): vouched.append("review")
        if not news: return None
        who = [w for w in dict.fromkeys(who) if w]
        # when the repository's own side last spoke in this batch: the newest stamp among the vouched items only. The thread's updated_at (the event's time before) also moves for a stranger's later comment, which would stamp an
        # earlier comment by the owner's side at the stranger's time. A merge keeps the thread's time (the merge is no comment's).
        own_stamps = [(x.get(k), _ts(x.get(k))) for xs, k in ((cs, "created_at"), (rv, "submitted_at"), (rc, "created_at")) for x in xs if _events.trusted_association(x.get("author_association")) and _ts(x.get(k))]
        vstamp = "" if "pr_merged" in types or not own_stamps else max(own_stamps, key=lambda t: t[1])[0]
        return "; ".join(news), ", ".join(who[:3]) or "someone", link, "+".join(types), (_merges.refs(i.get("body")) if "pr_merged" in types else []), "+".join(vouched), vstamp      # the board ids the merged pull request's body names: the issue read above already holds the body
    def notifications(a_id):
        """A repo root (anchoring a repo as a whole: whatever activity the owner's GitHub account gets notified
        of): the repo's notification threads of the owner's account (all=true, read-only), relying on GitHub's own subscription
        logic. An issue/PR thread reports only other people's comments and reviews and a merge or close; CI (ci_activity, on when
        the account notifies on Actions, failed workflows only) and other thread kinds come as GitHub words them. One thread
        update, one notice. Threads another anchor on the repo already watches (#N, @releases) are skipped. First sight seeds."""
        repo = a_id[7:-14]
        npath = f"/repos/{repo}/notifications?all=true&per_page=50"
        nstate, ntok, _, nsig = notif_access()
        if nstate == "bad": return                            # not read (the setting's file is unusable, or its token was refused: said on the anchor); not a failed look, so not tried again every pass
        try: ns = gh(npath, conditional=True, token=ntok)
        except Exception as e:
            if refusal(e, ntok): note_refusal(nsig); return   # GitHub's answer, not a failed look: no retry until the file changes
            log.warning("github %s: %s", a_id, str(e)[:120]); failed[0] = True; return
        if ns is None: return                                 # 304: nothing new
        st = state.setdefault(a_id, {"threads": None, "said": {}})
        seen = st["threads"]
        if seen is None:
            st["threads"] = {x["id"]: x.get("updated_at") for x in ns}; log.info("github %s: seeded with %d threads", a_id, len(ns)); return
        with hub.lock: bound = {_anc.anchor_id(k) or k for k in hub.bindings if k.startswith("github:")}   # by the current name of each repo ([github.moved]), as the lookups below
        cid = lambda a: _anc.anchor_id(a) or a
        for x in ns:
            if held() > 0: etags.pop(npath, None); break           # the read cap is spent: the threads not looked at stay unseen, and the list is read in full again next pass (no ETag kept)
            learn(repo, x.get("repository"))
            prev = seen.get(x["id"])
            if prev == x.get("updated_at"): continue
            seen[x["id"]] = x.get("updated_at")
            sub = x.get("subject") or {}; typ = sub.get("type") or ""; url = sub.get("url") or ""; title = (sub.get("title") or "")[:90]
            m = re.search(r"/(?:issues|pulls)/(\d+)$", url)
            if m and cid(f"github:{repo}#{m.group(1)}") in bound: continue          # the issue/PR anchor already reports it
            if typ == "Release" and cid(f"github:{repo}@releases") in bound: continue
            body_refs, vouched, vstamp = [], "", ""
            if m:
                try: got = thread_news(repo, m.group(1), typ == "PullRequest", prev)
                except Exception as e:
                    log.warning("github %s #%s: %s", a_id, m.group(1), str(e)[:100])
                    if prev is None: seen.pop(x["id"], None)          # the thread was not looked at: it is new again next pass, not lost
                    else: seen[x["id"]] = prev
                    etags.pop(npath, None); continue
                if not got: continue                                             # only the owner's own pushes/edits, labels, CI on the thread
                text, who, link, etype, body_refs, vouched, vstamp = got; text = f"{text} on #{m.group(1)} \"{title[:70]}\""
            elif x.get("reason") == "ci_activity" or typ == "CheckSuite":       # GitHub's own CI notice (failed runs, as the owner set it): delivered
                text, who, link, etype = f"\"{title}\"", "CI", f"https://github.com/{repo}/actions", "ci_activity"
            else:                                                                # any other thread kind: unclassified, delivered
                text, who, link, etype = f"({x.get('reason')}) {typ} \"{title}\"", REASON.get(x.get("reason"), "update"), html_of(url) or f"https://github.com/{repo}", ""
            if st["said"].get(x["id"]) == text: continue                          # one thread update, one notice
            st["said"][x["id"]] = text
            hub.event(a_id, {"title": repo.split('/')[1], "who": who, "text": text, "url": link, "ts": vstamp or x.get("updated_at"), "etype": etype, "repo_id": rid(repo), "vouched": vouched, **({"meta": {"refs": body_refs}} if body_refs else {})}, kind="github-state")
    FAIL =("failure", "timed_out", "action_required", "startup_failure", "stale")
    def pr_meta(c):
        """The head branch and author of the watched pull request, from the CI state `c` of its anchor (its last read of the PR; {} until it has been read): added to every event on the PR."""
        return {k: c[k] for k in ("head_ref", "author") if (c or {}).get(k)}
    def commit_seen(a_id, repo, n, c, down, title=None):
        """The head commit of a watched pull request changed (a push, or a force-push to another commit, an old commit included): record it as the item's last activity. GitHub sends no push notification, so this is the only
        place it is seen. Found live, it is stamped at the time the hub saw it, with no request: the push is what happened now, whenever the commit was made. Found after the hub was away (`down`: its last look at this pull
        request is older than COMMIT_DOWNTIME or unknown), the commit is read once for its committer date (never later than now, never older than the event log's window); a read that fails (the hourly cap, a refusal, an
        unreadable date) stamps the time seen instead, so the signal is not lost. Only a branch of the repository itself counts (nothing is read or recorded for a fork's pull request). The event is record_only: written to the event log and told to no one (Hub.emit)."""
        if not c.get("own_branch"): return
        now = time.time(); when = now
        if down:
            try: cm = gh(f"/repos/{repo}/git/commits/{c['sha']}")
            except Exception as e: log.warning("github %s: commit %s: %s", a_id, c["sha"][:7], str(e)[:100])
            else:
                t = _events.commit_time(((cm.get("committer") or {}) if isinstance(cm, dict) else {}).get("date"), now)
                if t is not None: when = t
        if not title:
            with hub.lock: title = ((hub.status.get("anchors") or {}).get(a_id) or {}).get("title") or f"{repo.split('/')[1]}#{n}"
        hub.event(a_id, {"title": title, "who": c.get("author") or "someone", "text": f"new commit {c['sha'][:7]}", "url": f"https://github.com/{repo}/pull/{n}", "ts": when, "etype": "pr_commit", "repo_id": rid(repo), "vouched": "commit", "record_only": True, **pr_meta(c)}, kind="github-state")
    issue_gone: set[str] = set()                      # anchors whose issue read answered 404 at the last look (memory only: a restart asks once more)
    def gone_404(e): return bool(GONE.search(str(e)))
    def verdict_seen(a_id, repo, title, c):
        """A pull request comment just read: when its first line is a verification verdict (event_log.is_verdict) and its author is the hub's own login or the repository's own side, record it for the item's last
        activity. record_only: written to the event log and told to no one (Hub.emit); the comment's own notice, when there is one, goes as before. No request of its own."""
        if not _events.is_verdict(c.get("body")): return
        who = (c.get("user") or {}).get("login") or ""
        if not ((me and who == me) or _events.trusted_association(c.get("author_association"))): return
        hub.event(a_id, {"title": title, "who": who, "text": "verification verdict", "url": c.get("html_url") or "", "ts": c.get("created_at"), "etype": "pr_verdict", "repo_id": rid(repo), "vouched": "verdict", "record_only": True}, kind="github-state")
    def ci(a_id, repo, n, key=None, title=None):
        """CI on a watched pull request (a failed run can otherwise go unnoticed). One notice per head
        commit once all its check runs have finished, naming the failed ones (canceled ones counted, not a trigger); a later
        commit that passes after a failure gets one "passing again", and one that passes after a passing commit gets one "passing on"
        (a green result is activity on the item whatever the head before it was): that one is record_only, written to the event log and
        delivered to no one, so a green on every push wakes nothing. First sight seeds silently when CI has already finished; when it was
        still running, the first finished result is reported (c["pending"])."""
        ck = key or a_id
        c = ci_st.setdefault(ck, {"pr": None, "sha": None, "key": None})
        now = time.time()
        if c["pr"] is not True and ((state.get(a_id) or {}).get("pr") is False or a_id in issue_gone): return      # the issue read found an issue, or found nothing under this number: no pull request can be there (a pull request is an issue too), so none is asked for
        if c["pr"] is False:                                  # no pull request under this number as of the last look: asked again after a wait (one that did not exist yet may have been opened since)
            age = now - c.get("missing", now)
            if now - c.get("tried", 0) < (RECHECK_FAST if age < RECHECK_FAST_FOR else RECHECK_SLOW if age < RECHECK_SLOW_FOR else RECHECK_DAILY): return
            etags.pop(f"/repos/{repo}/pulls/{n}", None)       # asked in full: an ETag from before the miss (an entry saved by an earlier version) must not turn the answer into a 304 the entry cannot read
        try: p = gh(f"/repos/{repo}/pulls/{n}", conditional=True)
        except Exception as e:
            if not gone_404(e): failed[0] = True      # not an answer (GitHub's error, a refusal, the cap): the look at the anchor is not a read, as for the issue
            else:
                ci_st[ck] = c = {**{k: v for k, v in c.items() if k not in PR_FIELDS}, "pr": False, "missing": c.get("missing", now), "tried": now}      # one replacement: the minute's snapshot sees the entry before or after, never half of it; nothing of an earlier pull request stays to be put on a notice
                etags.pop(f"/repos/{repo}/pulls/{n}", None); committed.get(a_id, {}).pop(f"/repos/{repo}/pulls/{n}", None)      # the saved copy of the ETag goes too (settle() only adds what is still held, and a read that failed after its 200 keeps the older saved one on purpose): a restart must not answer 304 for what is gone
            return
        if c["pr"] is False and p is not None: ci_st[ck] = c = {"pr": None, "sha": None, "key": None}      # the pull request exists now: a first sight, with nothing from before it
        last, c["looked"] = c.get("looked"), time.time()      # when this pull request was last looked at (kept with the CI state, so it survives a restart): a head that changed after a gap was missed, not seen live
        if p is not None:
            c["pr"] = True
            learn(repo, (p.get("base") or {}).get("repo"))
            was = c.get("sha")
            if (p.get("head") or {}).get("sha"): c["sha"] = p["head"]["sha"]
            c["head_ref"], c["author"] = str((p.get("head") or {}).get("ref") or ""), str((p.get("user") or {}).get("login") or "")      # whose pull request it is (a builder's branch is prefixed with its name); kept with the CI state, so a 304 later still knows
            hr, br = (str((((p.get(k) or {}).get("repo")) or {}).get("full_name") or "").lower() for k in ("head", "base"))
            c["own_branch"] = bool(hr) and hr == br      # the head branch is in the repository itself, not a fork's (a deleted fork has no head repo, and a payload that does not say names none): only then is a CI result the repository's own side moving
            if was and c["sha"] != was: commit_seen(a_id, repo, n, c, last is None or c["looked"] - last > COMMIT_DOWNTIME, title)      # the head commit changed since the last read of this pull request (a first sight has no earlier sha and records nothing; a 304 has no payload and records nothing)
        if not c.get("sha"): return
        try: r = gh(f"/repos/{repo}/commits/{c['sha']}/check-runs?per_page=100", conditional=True)
        except Exception as e:
            if not gone_404(e): failed[0] = True      # a commit GitHub no longer has (a forced push) is an answer; anything else is not a look
            return
        if r is None: return
        runs = r.get("check_runs") or []
        if not runs or any(x.get("status") != "completed" for x in runs):      # still running: wait for the whole set
            if c["key"] is None: c["pending"] = True      # first sight with CI still running: nothing is seeded, so the first finished result is reported, not swallowed as a seed
            return
        bad = sorted(x["name"] for x in runs if x.get("conclusion") in FAIL)
        canc = sum(1 for x in runs if x.get("conclusion") == "cancelled")
        key = (c["sha"], tuple(bad))
        prev, c["key"] = c["key"], key
        waited = bool(c.pop("pending", None)) and prev is None      # CI was running when the pull request was first looked at: this is its first finished result
        if (prev is None and not waited) or key == prev: return
        if not title:
            with hub.lock: title = (hub.status["anchors"].get(a_id) or {}).get("title") or f"{repo.split('/')[1]}#{n}"
        url = f"https://github.com/{repo}/pull/{n}/checks"
        if bad:
            text = f"failed on {c['sha'][:7]}: {len(bad)} of {len(runs)} checks — " + ", ".join(bad[:6]) + (" …" if len(bad) > 6 else "") + (f" ({canc} canceled)" if canc else "")
        elif prev and prev[1]:
            text = f"passing again on {c['sha'][:7]} ({len(runs)} checks{f', {canc} canceled' if canc else ''})"
        else:
            text = f"passing on {c['sha'][:7]} ({len(runs)} checks{f', {canc} canceled' if canc else ''})"      # a new head that is green after a green one, or the first finished result: ci_passed for the event log (and the item's last activity), record_only so nothing is delivered
        fin = max((x["completed_at"] for x in runs if _ts(x.get("completed_at"))), key=_ts, default=None)      # when the last check run finished: a result seen after downtime keeps its own time; one outside the event log's window (a day old, an hour ahead) is the hub's, as before
        hub.event(a_id, {"title": title, "who": "CI", "text": text, "url": url, "ts": fin if fin and _events.event_time(fin, time.time()) is not None else now_iso(), "etype": "ci_failed" if bad else "ci_passed", "repo_id": rid(repo), "vouched": ("ci_failed" if bad else "ci_passed") if c.get("own_branch") else "", **({"record_only": True} if not bad and not (prev and prev[1]) else {}), **pr_meta(c)}, kind="github-state")
    def snap(i):
        """What is saved of an issue or pull request between looks (`merged` and `pr`, kept to tell a finished anchor from a closed pull request that can still be reopened and merged)."""
        pr = i.get("pull_request")
        return {"state": i["state"], "comments": i["comments"], "updated": i["updated_at"], "pr": bool(pr), "merged": bool((pr or {}).get("merged_at"))}
    def owes(a_id):
        """Whether a list may owe the anchor a full read: its saved state is of a finished anchor, or there is none (an open anchor is read every pass anyway)."""
        st = state.get(a_id)
        return st is None or finished(st)
    def list_read(repo, key, since):
        """The issues and pull requests of `repo` changed since `since` (less LIST_OVERLAP), the oldest change first, paged through gh() → ({number: issue}, the ETags of the first page); the issues are None when the
        first page answers 304 (the list is what the last whole read showed). The first page is read conditionally, the others are not (a 304 of the first says nothing of a later page when the list ran on)."""
        q = f"/repos/{repo}/issues?state=all&since={zulu(_ts(since) - LIST_OVERLAP)}&sort=updated&direction=asc&per_page={LIST_PER_PAGE}"
        tags = dict(list_tags.get(key) or {}); out: dict[int, dict] = {}
        for page in range(1, LIST_PAGES + 1):
            got = gh(q if page == 1 else f"{q}&page={page}", conditional=page == 1, tags=tags if page == 1 else None)
            if got is None: return None, tags
            if not isinstance(got, list): raise ValueError("the list of issues was not answered as a list")
            for it in got:
                if isinstance(it, dict) and isinstance(it.get("number"), int): out[it["number"]] = it
            if len(got) < LIST_PER_PAGE: return out, tags
        raise TooManyChanges(f"more than {LIST_PAGES * LIST_PER_PAGE} issues changed")
    def list_plan(repo):
        """The list of `repo` for this pass, read once (the first finished anchor of the repo that is looked at asks for it) → {"ok", "items"}. With a position younger than LIST_MAX_AGE it is one list read
        from the position on, and the anchors the list shows (those bound) are owed a full read. With none, or an old one, it is the fallback: the position is made from the newest change GitHub shows (before any
        anchor is read, so a read of an anchor is never older than the position), and every issue and pull request anchor of the repo that may be finished is owed a full read, paced like a catch-up. A read that
        fails (not an answer GitHub could give: a 5xx, a refusal, the cap) leaves the position as it was and the repo's finished anchors unread, not marked read: the next pass asks again."""
        key = repo.lower(); p = plan.get(key)
        if p is not None: return p
        plan[key] = p = {"ok": False, "items": {}}
        now = time.time(); cur = cursors.get(key); mine = pass_ids.get(key, {})
        try:
            if cur is None or now - cur["at"] > LIST_MAX_AGE:
                top = gh(f"/repos/{repo}/issues?state=all&sort=updated&direction=desc&per_page=1")
                if not isinstance(top, list): raise ValueError("the newest issue was not answered as a list")
                since = str(top[0].get("updated_at") or "") if top and isinstance(top[0], dict) else ""
                cursors[key] = {"since": since if _ts(since) > 0 else zulu(now), "at": now, "owed": {a for a in mine.values() if owes(a)}, "catch": True}
                list_tags.pop(key, None)
            else:
                items, tags = list_read(repo, key, cur["since"])
                owed, since = set(cur["owed"]), cur["since"]
                if items is not None:
                    p["items"] = {str(n): it for n, it in items.items()}
                    owed |= {a for n, a in mine.items() if n in p["items"] and owes(a)}
                    newest = max((it.get("updated_at") for it in items.values()), key=lambda z: _ts(z) if isinstance(z, str) else 0.0, default=None)
                    if isinstance(newest, str) and _ts(newest) > _ts(since): since = newest
                cursors[key] = {"since": since, "at": now, "owed": owed & set(mine.values()), "catch": cur["catch"]}      # one replacement: the minute's snapshot sees it before or after, never half of it
                list_tags[key] = tags
            p["ok"] = True; listed[0] = True
        except Exception as e:
            log.warning("github %s: issue list: %s", repo, str(e)[:120]); list_tags.pop(key, None)
            if isinstance(e, TooManyChanges): cursors.pop(key, None)      # too much to page through: the fallback is cheaper, and asked for at the next pass
            if "rate limit" in str(e).lower(): hub.hold("github", BACKOFF); time.sleep(BACKOFF)
        return p
    def catching(a_id):
        """Whether the anchor's read is the fallback's (a finished anchor of a repo with no usable list position, or one still owed its read by the fallback): paced like a catch-up's."""
        if a_id.endswith("@releases") or a_id.endswith("@notifications"): return False
        e = cursors.get(split(a_id)[0].lower())
        if e is None or time.time() - e["at"] > LIST_MAX_AGE: return finished(state.get(a_id))
        return bool(e["catch"] and a_id in e["owed"])
    def how(a_id):
        """how an anchor is looked at in this pass → "skip" | "issue" | "full" | "wait". A FINISHED anchor — a closed issue or pull request, merged or not (what can still happen to it is a late
        comment, a reopening, a merge after one) — is read (CI, issue, comments) only when its repo's list shows it changed (its saved state differs from what the list shows of it) or a read of it is
        still owed (list_plan); otherwise it costs nothing. An anchor not in `looked` (a catch-up: the first start, a change of login) is read, never skipped: the pacing in one_pass lets it through as a read to be paid for,
        and a skip would put it in `looked` unread. "wait": the repo's list could not be read, so nothing is known of the anchor: not read, not marked read, asked for again next pass. An anchor with no saved state is read now
        and seeded, and one saved before `merged` was kept (state without it) is read as an issue only, once, to learn it."""
        st = state.get(_anc.anchor_id(a_id) or a_id) or {}
        if st.get("state") != "closed": return "full"
        if "merged" not in st: return "issue"
        repo, n = split(a_id); p = list_plan(repo)
        if a_id not in looked: return "full"
        if not p["ok"]: return "wait"
        it = p["items"].get(n)
        if it is not None:
            try: return "skip" if snap(it) == st else "full"
            except Exception: return "full"      # a list entry that does not say what the saved state needs: the anchor is read itself
        return "full" if a_id in cursors[repo.lower()]["owed"] else "skip"
    late_failed: dict[str, int] = {}                  # anchor id → tries of its late merge line that failed (memory only: a restart gives a few more, no more)
    def logged_merge(repo, n):
        """Which logs hold this pull request's merge already (written by another anchor on it, the repository's notifications, an earlier try or start)? → (merge log, event log). Each is read from its start: a merge found late is rare.
        Only a `merged` line of the event log counts (a comment's or a CI result's line is no merge)."""
        key = (_cfg.canon_repo(repo), int(n)); out = []
        for rows, kind in ((_merges.read(0)[0], None), (_events.read(0)[0], "merged")):
            found = False
            for r in rows:
                try:
                    if (kind is None or r.get("kind") == kind) and (_cfg.canon_repo(r.get("repo")), int(r.get("n"))) == key: found = True; break
                except Exception: continue
            out.append(found)
        return tuple(out)
    def late_merge(a_id, repo, n, i):
        """The anchor was first read (the seed in `watch`) on a pull request that has merged already. A merge within LATE_MERGE_S, at most LATE_SKEW ahead of the hub's clock, gets its merge line now in each log that does not hold it, so an anchor added
        after the merge still counts it (the item it is scoped to is credited by the same tie as for any merge: an anchor scoped to items ties them, a project-wide one none). Recorded only (Hub.record): the sessions
        of the anchor are not told. The event log's line is stamped at the time it merged, and so is the merge log's (the server's merge pass skips a merge older than its floor, so a merge of 20 hours ago credits
        last activity but is not recorded by the merge pass). The body's refs are not read: it can be edited long after the merge, and the anchor's own scope is the tie here. A pull request still open, closed unmerged, merged
        longer ago or at an unreadable or future time is a silent seed, as before. → False when the line could not be written: the caller does not seed, so the next pass reads the pull request again."""
        try:
            merged = (i.get("pull_request") or {}).get("merged_at")
            at, now = _ts(merged), time.time()      # one reading: the window here and the event log's own window are the same test
            if not merged or at <= 0 or at > now + LATE_SKEW or now - at > LATE_MERGE_S: return True
            has_merge, has_event = logged_merge(repo, n)
            if has_merge and has_event: return True      # nothing to write: the logs hold it (a try that failed between the two writes writes only the log that lacks it)
            if not hub.record(a_id, {"title": f"{repo.split('/')[1]}#{n} \"{str(i.get('title') or '')[:50]}\"", "who": (i.get("closed_by") or {}).get("login") or "someone", "text": "merged it", "url": i.get("html_url") or f"https://github.com/{repo}/pull/{n}",
                                     "ts": merged, "etype": "pr_merged", "repo_id": rid(repo), **pr_meta(ci_st.get(a_id))}, kind="github-state", now=now, at=min(at, now), merge_log=not has_merge, event_log=not has_event):
                return False
            log.info("github %s: merged %d min ago, before the anchor was added: merge line written", a_id, int(now - at) // 60)
            return True
        except Exception as e:
            log.warning("github %s: late merge line not written: %s", a_id, str(e)[:120]); return False
    def watch(a_id, with_ci=True):
        """One look at an issue or pull request anchor: its CI (unless `with_ci` is off), then the issue itself (state, comments)."""
        repo, n = split(a_id)
        if with_ci:
            try: ci(a_id, repo, n)
            except Exception as e: log.warning("github ci %s: %s", a_id, str(e)[:120])
        try:
            try: i = gh(f"/repos/{repo}/issues/{n}", conditional=True)
            except Exception as e:
                if not gone_404(e): errs.append(str(e))      # the issue read itself failed: what says, after the look, that GitHub refused the anchor (a failed CI or comment read does not: the anchor is read)
                if gone_404(e):
                    nothing[0] = True
                    issue_gone.add(a_id)      # nothing under this number (yet): the pull request read leaves it alone until the issue read finds something
                    if a_id in state: suspect.setdefault(a_id, time.time())      # …and one that was read before may be gone for good: when it first showed is kept, and the server's anchor sweep is told only once another read of the repository has answered since (repos_record)
                raise
            repo_ok[repo.lower()] = time.time(); issue_gone.discard(a_id); gone.pop(a_id, None); suspect.pop(a_id, None)
            if i is None: return                         # 304: nothing changed
            learn(repo, i.get("repository"))
            st = state.get(a_id)
            if st is None:                                # first sight seeds; a merge of the last day gets its merge line before the seed, and a line that could not be written leaves the anchor unseeded and its ETag dropped, so the next pass reads it again
                if late_merge(a_id, repo, n, i): state[a_id] = snap(i)
                else:
                    late_failed[a_id] = late_failed.get(a_id, 0) + 1      # per anchor
                    if late_failed[a_id] >= LATE_TRIES:
                        state[a_id] = snap(i); log.warning("github %s: the late merge line could not be written in %d tries; dropped, the anchor is seeded without it", a_id, LATE_TRIES)
                    else: etags.pop(f"/repos/{repo}/issues/{n}", None)
                return
            if (i["state"], i["comments"], i["updated_at"]) != (st["state"], st["comments"], st["updated"]): resolved.pop(a_id, None)      # the saved label of a finished anchor is made again at the next start
            title = f"{repo.split('/')[1]}#{n} \"{i['title'][:50]}\""
            if i["comments"] > st["comments"]:
                for c in gh(f"/repos/{repo}/issues/{n}/comments?since={st['updated']}&per_page=20"):
                    # `since` is inclusive of the seed instant, so the comment that set the seeded updated_at
                    # comes back on the next change (an old comment would come back as new): only
                    # comments created after the last observed state are new
                    if _ts(c.get("created_at")) <= _ts(st.get("updated")): continue
                    if i.get("pull_request"): verdict_seen(a_id, repo, title, c)      # before the own-login skip: the sessions post their verdicts as that login
                    if c["user"]["login"] == me and not os.environ.get("ANCHOR_HUB_ALLOW_SELF"): continue
                    body = (c.get("body") or "").replace("\n", " ")
                    hub.event(a_id, {"title": title, "who": c["user"]["login"], "text": body[:140] + ("…" if len(body) > 140 else ""), "url": c["html_url"], "ts": c["created_at"], "etype": "comment", "repo_id": rid(repo), "bot": (c.get("user") or {}).get("type") == "Bot", "vouched": "comment" if _events.trusted_association(c.get("author_association")) else "", **pr_meta(ci_st.get(a_id))}, kind="github")
            merged_now = bool((i.get("pull_request") or {}).get("merged_at"))
            if i["state"] != st["state"] or (merged_now and st.get("merged") is False):      # …or closed again by a merge after a reopening that fell between two looks
                who = (i.get("closed_by") or {}).get("login") or "someone"
                verb = "merged" if (i.get("pull_request") or {}).get("merged_at") else i["state"]
                etype = ("pr_" if i.get("pull_request") else "issue_") + {"merged": "merged", "closed": "closed"}.get(verb, "reopened")
                hub.event(a_id, {"title": title, "who": who, "text": f"{verb} it", "url": i["html_url"], "ts": i["updated_at"], "etype": etype, "repo_id": rid(repo), **({"meta": {"refs": _merges.refs(i.get("body"))}} if verb == "merged" else {}), **pr_meta(ci_st.get(a_id))}, kind="github-state")
            state[a_id] = snap(i)
        except Exception as e:
            log.warning("github %s: %s", a_id, str(e)[:120])
            if not gone_404(e): failed[0] = True                 # nothing under that number is an answer (read again later by the poll's own schedule); any other failure is not a look
            etags.pop(f"/repos/{repo}/issues/{n}", None)         # a read that failed after the issue's 200 (the comments, refused by the cap or GitHub) is made again next pass, not answered 304
            if "rate limit" in str(e).lower() or "403" in str(e): hub.hold("github", BACKOFF); time.sleep(BACKOFF)
    hub.hold("github", FIRST_PASS)                         # the first pass after a start reads every anchor: the board counts no age until it ends or this time is up
    hub.gh_state = {"ci": ci_st, "state": state, "etags": etags, "news": thread_news, "committed": committed, "resolved": resolved, "looked": looked, "lists": cursors}      # for inspection and tests
    capped_now = [False]                                                # the cap warning is logged when the state changes, not every pass
    catching_now = [False]                                              # the catch-up is logged when it begins and when it ends, not every pass
    retry: dict[str, tuple[int, float]] = {}                            # anchor id → (looks that failed in a row, when it is tried next): memory only, a restart gives each a few more tries
    hub.gh_state["retry"] = retry
    def fails(a_id): return retry.get(a_id, (0, 0.0))[0]
    def one_pass():
        """One poll over every anchor. A CATCH-UP (a first start, a change of login, anchors bound for the first time: every anchor not in `looked`) reads anchors in turn, the ones never read
        first, and starts another only while `paced()` allows, so it never takes more than CATCHUP_SHARE of the hour's reads; the rest wait for the next pass, and a catch-up the hour's reads cannot yet
        finish is shown on the card as healthy, with a note of how far it is. The anchors already read are looked at in every pass, the one read longest ago first, whatever the catch-up has left."""
        # GitHub answers the user's notifications API only to a person's sign-in (an App's installation token is refused it with a 403, always), so with an App token a repo's `@notifications` anchor can only be read with the
        # token of `[anchor_hub] notifications_token_file`: with none set it is not read here, so it costs no call, no count and no note on the card, and each anchor says on its own status why it is not read. A person's token binds them as ever. A file that is set but not usable
        # (or whose token GitHub refused) leaves them unbound too, and their status says why.
        nstate, _, nwhy, _ = notif_access()
        if (nstate, nwhy) != notif_said[0]:
            notif_said[0] = (nstate, nwhy)
            if nstate == "bad" and nwhy != NOTIF_REFUSED_WHY: log.warning("github: %s", nwhy)      # a refusal has its own line (note_refusal)
            elif nstate == "ok": log.info("github: the notification anchors are read with the token of %s", NOTIF_SETTING)
        notif_on = nstate == "ok" or (nstate == "off" and not app_token)
        with hub.lock: ids = [k for k in hub.bindings if k.startswith("github:") and (notif_on or not k.endswith("@notifications"))]
        for k in notif_anchors(): flag(k, nwhy if nstate == "bad" else NOTIF_OFF_WHY if nstate == "off" and app_token else None)      # an unusable file, a refused token and a declined bind alike: the anchor is said unreadable from the first pass that would have bound it
        # never read first (as bound), then by when each was last read, the longest ago first; within each, an anchor whose looks keep failing goes behind the ones that do not (sorted() is stable: the order bound is kept)
        ids = sorted((a for a in ids if a not in looked), key=fails) + sorted((a for a in ids if a in looked), key=lambda a: (fails(a), looked[a]))
        pass_ids.clear(); plan.clear(); listed[0] = False
        for a_id in ids:
            if not (a_id.endswith("@releases") or a_id.endswith("@notifications")): repo, n = split(a_id); pass_ids.setdefault(repo.lower(), {})[n] = a_id
        skipped = False; paced_out = False                          # paced_out: no anchor not yet read is started in this pass
        t0 = time.time(); bad: list[str] = []; answered = False     # bad: the anchors whose look failed in this pass; answered: a look in it that GitHub answered (a failure of every look is an outage, and no anchor's)
        for a_id in ids:
            if held() > 0:                                          # the hourly read cap is spent: the rest of this pass reads nothing; the next pass looks again
                skipped = True; break
            adopt(state, a_id); adopt(ci_st, a_id); adopt(looked, a_id)           # before release, notifications, ci and the issue read look at either
            if retry.get(a_id, (0, 0.0))[1] > t0: continue      # its looks keep failing: not before its time (it reads as unread, or as it was, meanwhile)
            if (a_id not in looked or catching(a_id)) and (paced_out or paced() > 0):   # not read yet (or a finished anchor the fallback has still to read), and the catch-up has had its share of the hour: it waits for room, and the anchors already read go on
                paced_out = True; continue
            touched.clear(); errs.clear(); nothing[0] = False; failed[0] = False; asked = True
            if a_id.endswith("@releases"): release(a_id)
            elif a_id.endswith("@notifications"): notifications(a_id)      # CI: GitHub's own ci_activity
            elif (mode := how(a_id)) == "wait": continue          # its repo's list could not be read: nothing is known of it, so it is not read and not marked read
            elif mode != "skip": watch(a_id, with_ci=mode == "full")
            else: asked = False
            settle(a_id)
            if not a_id.endswith("@notifications") and asked:      # a refused read (or a number with nothing under it) is said on the anchor, a read that went through takes it back: the anchors service's own retry then decides whether it counts (two refusals, minutes apart)
                why = next((w for w in (refusal_why(e) for e in errs) if w), "") if failed[0] else notfound_why() if nothing[0] else ""
                if why: flag(a_id, why)
                elif not failed[0]: flag(a_id, None)
            if failed[0]: bad.append(a_id)                      # a look that failed is not a read: the anchor stays unread (or keeps its old turn) and is tried again
            else:
                looked[a_id] = time.time(); retry.pop(a_id, None); answered = answered or asked
                if not (a_id.endswith("@releases") or a_id.endswith("@notifications")) and (ent := cursors.get(split(a_id)[0].lower())):
                    ent["owed"].discard(a_id)                   # read in full (or shown unchanged by the list): no longer owed
                    if not ent["owed"]: ent["catch"] = False
        answered = answered or listed[0]                        # a list that GitHub answered is a look too
        for a_id in bad:                                       # every failed look is counted (an anchor that failed goes behind those that did not); the wait between tries starts only in a pass in which GitHub answered another look: if it answered none, it may be down, and the anchors are tried again next pass
            n = fails(a_id) + 1; retry[a_id] = (n, t0 + min(RETRY_MAX, RETRY_FIRST * 2 ** (n - RETRY_AFTER)) if answered and n >= RETRY_AFTER else 0.0)
        for a_id in [a for a in retry if a not in ids]: del retry[a_id]      # no longer bound
        if skipped:                                                # a pass the cap cut short is not a finished check
            msg = f"reads held by the hourly cap, resume in {_gb.held_words(held())}"
            if not capped_now[0]: log.warning("github: %s; this pass is cut short", msg)
            capped_now[0] = True; hub.health("github", False, msg)
        else:
            if capped_now[0]: log.info("github: the hourly cap on reads has room again; polling resumes")
            capped_now[0] = False
            with hub.lock: hub.status.setdefault("github", {})["last_pass"] = time.time()
            # A catch-up is no failure either: the anchors it has not reached wait for the hour's reads, and the note says how far it is (it is gone once every anchor has been read).
            # An anchor whose looks keep failing is no part of it (it would read "n-1 of n" for good): it is said apart, as tried less often.
            unread = [a for a in ids if a not in looked]; stuck = [a for a in ids if retry.get(a, (0, 0.0))[1] > 0]; open_ = [a for a in unread if a not in stuck]
            catch_note = f"catching up: {len(ids) - len(unread)} of {len(ids) - len(unread) + len(open_)} anchors read" if open_ else None
            stuck_note = f"{len(stuck)} anchor{'s' if len(stuck) != 1 else ''} could not be read, tried again less often" if stuck else None
            if catch_note and not catching_now[0]: log.info("github: %s; it keeps the hour's reads under %d%% of the budget and goes on as they expire", catch_note, round(CATCHUP_SHARE * 100))
            elif not catch_note and catching_now[0]: log.info("github: caught up: every anchor that can be read has been read")
            catching_now[0] = bool(catch_note)
            hub.health("github", True, "; ".join(n for n in (catch_note, stuck_note) if n) or None)      # a finished poll pass is GitHub's real check
    def loop():
        # A pass that raises (a status file that could not be written, a bug) is logged and the next pass runs: the poll thread never ends on one.
        # The pause is on the dot: every poll fires at :00 s (conditional GETs: unchanged issues cost nothing); time.sleep is looked up at each call.
        guarded_loop(hub, "github", one_pass, every=lambda: GHPOLL - time.time() % GHPOLL, retry=GHPOLL, sleep=lambda s: time.sleep(s))
    threading.Thread(target=loop, daemon=True).start()
