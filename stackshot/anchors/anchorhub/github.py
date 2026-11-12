"""anchorhub.github — GitHub through the gh CLI: issues and PRs (comments, state, CI), a repo's releases, a repo's notifications."""
import json, os, re, subprocess, threading, time, zlib
from .core import Hub, Transient, _anc, _cfg, _events, _merges, _ts, guarded_loop, log, now_iso, now_iso_at
from stackshot.core import ghbudget as _gb   # the host's one hourly ledger of GitHub calls, shared with the stackshot server (a locked file under <state>/github)

GHPOLL = 60   # s; conditional GETs — a 304 does not count against the API budget
FIRST_PASS = 600   # s; how long the first pass after a start may take before the board counts the silence (announced with hub.hold, cleared by the pass's own check)
BACKOFF = 600   # s; the wait after GitHub refuses a read for its rate limit (announced to the board with hub.hold, so it is not shown stale)
FINISHED_EVERY = 10   # a closed or merged anchor is looked at once in this many passes (staggered by anchor), not every pass
PER_ANCHOR_ETAGS = 6  # ETags kept in the saved file per anchor (pull request, check runs of the newest commit, issue: three in use)
def run(hub: Hub):
    etags: dict[str, str] = {}
    # the ETags survive a restart, so the first pass after one is answered 304 (free) for every anchor that did not change, not a full 200 (counted)
    # for each of them. An ETag is saved only once the pass has finished with the anchor it belongs to (`committed`, filled by settle()): a save in the
    # middle of a read (the clean stop of a restart, the minute's save) never holds an ETag whose answer the saved state has not taken in yet, so a
    # change that arrives meanwhile is a 200 after the restart and is reported. A 304 needs no body: what the answer would have said is in the saved state.
    touched: list[str] = []                                # the conditional paths read for the anchor being looked at
    committed: dict[str, dict[str, str]] = {}              # anchor id → {path: ETag} as of its last finished look: what is saved
    resolved: dict[str, dict] = {}                         # anchor id → {path, etag, info}: the board's label, answered from here on a 304
    # GitHub's numeric repository ID (repository.id) survives a transfer to another owner; the anchor's owner/name does not. IDs are learnt from the
    # responses that carry one, by the repo name the anchor uses, and put on every event as repo_id (Event.repo_id, matched by [pilot] own_repos):
    # a notification thread's `repository`, a pull request's `base.repo`, an issue's `repository` when GitHub includes it. A release answer has none
    # (its event gets the ID only once another call on the same repo has seen it); an event with no ID is matched by name, as before.
    repo_ids: dict[str, int] = {}
    def learn(repo, obj):
        if isinstance(obj, dict) and isinstance(obj.get("id"), int) and not isinstance(obj.get("id"), bool) and obj["id"] > 0: repo_ids[repo.lower()] = obj["id"]
    def rid(repo): return repo_ids.get(repo.lower(), 0)
    def held():
        """Seconds until the hourly read cap has room (0 = it has): the cap is the ledger's, shared with the server (ghbudget.py, [github] read_budget)."""
        return _gb.wait(_gb.READ, _gb.read_cap())
    def counted(r):
        """A `gh` call GitHub answered goes into the ledger; a call that never reached it (no network) does not."""
        if r.returncode == 0 or not re.search(r"error connecting|could not resolve|timed? ?out|connection (refused|reset)", r.stderr or "", re.I): _gb.note(_gb.READ, caller="receivers")
    def gh(path, conditional=False, capped=True, tags=None):
        """`tags`: the ETags this read sends and updates (the poll's `etags` unless a caller keeps its own)."""
        if capped and (w := held()) > 0: raise RuntimeError(f"the hourly cap on GitHub reads is spent; reads resume in {_gb.held_words(w)}")
        tags = etags if tags is None else tags
        args = ["gh", "api", "-i", path] if conditional else ["gh", "api", path]
        if conditional and tags is etags: touched.append(path)
        if conditional and path in tags: args += ["-H", f"If-None-Match: {tags[path]}"]
        r = subprocess.run(args, capture_output=True, text=True, timeout=30)
        if conditional:
            head, _, body = r.stdout.partition("\n\n")
            if head.startswith("HTTP/") and " 304" in head.split("\n")[0]: return None        # unchanged, free: not in the ledger
            counted(r)
            for line in head.split("\n"):
                if line.lower().startswith("etag:"): tags[path] = line.split(":", 1)[1].strip()
            if r.returncode: raise RuntimeError((r.stderr or head).strip()[:120])
            return json.loads(body)
        counted(r)
        if r.returncode: raise RuntimeError(r.stderr.strip()[:120])
        return json.loads(r.stdout)
    try: me = gh("/user", capped=False)["login"]      # counted, never held: a spent cap must not read as "gh not authenticated" and turn the receiver off
    except subprocess.TimeoutExpired: raise Transient("gh api /user timed out")
    except Exception as e:
        # gh says "error connecting to api.github.com" when the network is down (DNS down at boot, which would be logged as "not
        # authenticated" and never retried): that is a Transient, tried again by start_receiver. Anything else (HTTP 401, not logged
        # in, no gh) is the credential: off, as before.
        if re.search(r"error connecting|githubstatus|could not resolve|timed? ?out|connection (refused|reset)|HTTP 5\d\d", str(e), re.I):
            raise Transient(str(e).replace("\n", " ")[:120])
        log.warning("github: gh not authenticated (%s) — receiver off", str(e)[:80]); return
    def split(a_id): repo, n = a_id[7:].rsplit("#", 1); return repo, n
    def html_of(api_url):
        """An API URL of an issue or PR → its github.com page."""
        return (api_url or "").replace("https://api.github.com/repos/", "https://github.com/").replace("/pulls/", "/pull/")
    def cached_get(a_id, path):
        """the resolver's read of `path` is conditional on the ETag saved with the last resolution of this anchor → (answer, ETag); an
        answer of None is a 304 (free): the saved resolution stands. The resolver's ETags are its own, apart from the poll's: a 200 here must not
        make the poll's next read of the same issue a 304 it never took in."""
        ent = resolved.get(a_id)
        tags = {path: ent["etag"]} if ent and ent.get("path") == path and ent.get("etag") else {}
        return gh(path, conditional=True, tags=tags), tags.get(path)
    def keep(a_id, path, tag, info):
        if tag: resolved[a_id] = {"path": path, "etag": tag, "info": info}
        return info
    def res(a_id):
        ent = resolved.get(a_id); cached = dict(ent["info"]) if ent and isinstance(ent.get("info"), dict) else None
        if a_id.endswith("@notifications"):
            repo = a_id[7:-14]; path = f"/repos/{repo}/notifications?all=true&per_page=50"
            try: ns, tag = cached_get(a_id, path)
            except Exception: ns, tag = [], None
            if ns is None and cached: return cached                      # 304: as last time
            ts = [_ts(x.get("updated_at")) for x in ns or [] if x.get("updated_at")]
            return keep(a_id, path, tag, {"title": f"{repo.split('/')[1]} notifications", "url": f"https://github.com/notifications?query=repo%3A{repo.replace('/', '%2F')}",
                                          "seen": now_iso_at(max(ts)) if ts else None})
        if a_id.endswith("@releases"):
            repo = a_id[7:-9]; path = f"/repos/{repo}/releases/latest"
            try: rl, tag = cached_get(a_id, path)
            except Exception: rl, tag = {}, None
            if rl is None and cached: return cached
            pub = (rl or {}).get("published_at")
            return keep(a_id, path, tag, {"title": f"{repo.split('/')[1]} releases", "url": f"https://github.com/{repo}/releases", "seen": now_iso_at(_ts(pub)) if pub else None})
        repo, n = split(a_id)
        if cached and (state.get(_anc.anchor_id(a_id) or a_id) or {}).get("state") == "closed": return cached      # a finished anchor is not asked again at start-up; the poll drops this when it sees it change
        path = f"/repos/{repo}/issues/{n}"
        try: i, tag = cached_get(a_id, path)
        except Exception as e:
            if not re.search(r"HTTP 4(04|10)", str(e)): return {"url": f"https://github.com/{repo}/issues/{n}"}    # not a refusal: tried again
            resolved.pop(a_id, None)
            return {"title": f"{repo}#{n}", "url": f"https://github.com/{repo}/issues/{n}", "unreadable": f"GitHub shows {me} no issue or pull request there"}
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
    def adopt(d, a_id):
        """[github.moved]: saved state, CI state and the like are keyed by the anchor id. When a pair is added while the hub runs (a config reload), the
        entry stored under the other name of the same repository is moved to the id the bindings use now, before it is read, so a run in flight, a
        comment or a merge in the gap is still reported and no entry is left under the dead name. An empty table: nothing is looked at, nothing moves."""
        if not _cfg.moved_repos(): return
        for k in [k for k in d if k != a_id and k.startswith("github:") and (_anc.anchor_id(k) or k) == (_anc.anchor_id(a_id) or a_id)]:
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
            for a, ent in (sv.get("resolved") or {}).items():
                if isinstance(ent, dict) and isinstance(ent.get("info"), dict) and isinstance(ent.get("etag"), str) and isinstance(ent.get("path"), str): resolved[_anc.anchor_id(a) or a] = ent
            for k, v in (sv.get("repo_ids") or {}).items():
                if isinstance(v, int) and not isinstance(v, bool) and v > 0: repo_ids[str(k).lower()] = v
        except Exception as e:
            log.warning("github: saved ETags not used (%s)", str(e)[:80]); committed.clear(); etags.clear(); resolved.clear()
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
                "etags": {a: dict(per) for a, per in list(committed.items()) if (_anc.anchor_id(a) or a) in bound and per},
                "resolved": {a: dict(e) for a, e in list(resolved.items()) if (_anc.anchor_id(a) or a) in bound}}
    hub.savers["github"] = snapshot
    hub.resolvers["github"] = res                          # last: the resolver reads `state` and the saved resolutions, which are restored above
    with hub.lock: hub.status["github"] = {"user": me, "since": now_iso()}; hub.push["github"] = {"mode": f"poll · {GHPOLL // 60} min"}
    log.info("github: ready as %s", me)
    def release(a_id):
        """Latest published release (drafts and prereleases excluded by the endpoint). The first observation
        seeds silently; a changed tag_name is one notice. A repo with no release yet (404) is seeded as none."""
        repo = a_id[7:-9]
        try: r = gh(f"/repos/{repo}/releases/latest", conditional=True)
        except Exception as e:
            if "404" in str(e) or "Not Found" in str(e): state.setdefault(a_id, {"tag": None}); return
            log.warning("github %s: %s", a_id, str(e)[:120])
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
        cs = others(gh(f"/repos/{repo}/issues/{n}/comments?{q}per_page=50"), "created_at")
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
        try: ns = gh(npath, conditional=True)
        except Exception as e:
            log.warning("github %s: %s", a_id, str(e)[:120]); return
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
    def ci(a_id, repo, n, key=None, title=None):
        """CI on a watched pull request (a failed run can otherwise go unnoticed). One notice per head
        commit once all its check runs have finished, naming the failed ones (cancelled ones counted, not a trigger); a later
        commit that passes after a failure gets one "passing again", and one that passes after a passing commit gets one "passing on"
        (a green result is activity on the item whatever the head before it was): that one is record_only, written to the event log and
        delivered to no one, so a green on every push wakes nothing. First sight seeds silently when CI has already finished; when it was
        still running, the first finished result is reported (c["pending"])."""
        c = ci_st.setdefault(key or a_id, {"pr": None, "sha": None, "key": None})
        if c["pr"] is False: return
        try: p = gh(f"/repos/{repo}/pulls/{n}", conditional=True)
        except Exception as e:
            if "404" in str(e) or "Not Found" in str(e): c["pr"] = False
            return
        if p is not None:
            c["pr"] = True
            learn(repo, (p.get("base") or {}).get("repo"))
            if (p.get("head") or {}).get("sha"): c["sha"] = p["head"]["sha"]
            c["head_ref"], c["author"] = str((p.get("head") or {}).get("ref") or ""), str((p.get("user") or {}).get("login") or "")      # whose pull request it is (a builder's branch is prefixed with its name); kept with the CI state, so a 304 later still knows
            hr, br = (str((((p.get(k) or {}).get("repo")) or {}).get("full_name") or "").lower() for k in ("head", "base"))
            c["own_branch"] = bool(hr) and hr == br      # the head branch is in the repository itself, not a fork's (a deleted fork has no head repo, and a payload that does not say names none): only then is a CI result the repository's own side moving
        if not c["sha"]: return
        try: r = gh(f"/repos/{repo}/commits/{c['sha']}/check-runs?per_page=100", conditional=True)
        except Exception: return
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
            text = f"failed on {c['sha'][:7]}: {len(bad)} of {len(runs)} checks — " + ", ".join(bad[:6]) + (" …" if len(bad) > 6 else "") + (f" ({canc} cancelled)" if canc else "")
        elif prev and prev[1]:
            text = f"passing again on {c['sha'][:7]} ({len(runs)} checks{f', {canc} cancelled' if canc else ''})"
        else:
            text = f"passing on {c['sha'][:7]} ({len(runs)} checks{f', {canc} cancelled' if canc else ''})"      # a new head that is green after a green one, or the first finished result: ci_passed for the event log (and the item's last activity), record_only so nothing is delivered
        fin = max((x["completed_at"] for x in runs if _ts(x.get("completed_at"))), key=_ts, default=None)      # when the last check run finished: a result seen after downtime keeps its own time; one outside the event log's window (a day old, an hour ahead) is the hub's, as before
        hub.event(a_id, {"title": title, "who": "CI", "text": text, "url": url, "ts": fin if fin and _events.event_time(fin, time.time()) is not None else now_iso(), "etype": "ci_failed" if bad else "ci_passed", "repo_id": rid(repo), "vouched": ("ci_failed" if bad else "ci_passed") if c.get("own_branch") else "", **({"record_only": True} if not bad and not (prev and prev[1]) else {}), **pr_meta(c)}, kind="github-state")
    def snap(i):
        """What is saved of an issue or pull request between looks (`merged` and `pr`, kept to tell a finished anchor from a closed pull request that can still be reopened and merged)."""
        pr = i.get("pull_request")
        return {"state": i["state"], "comments": i["comments"], "updated": i["updated_at"], "pr": bool(pr), "merged": bool((pr or {}).get("merged_at"))}
    def how(a_id, passno):
        """how an anchor is looked at in this pass → "skip" | "issue" | "full". A FINISHED anchor — a merged pull request or a closed issue (what can still happen
        to it is a late comment, or a closed issue's reopening) — is looked at (CI, issue, comments) once in FINISHED_EVERY passes, staggered
        by anchor so they do not all fall on one pass: a reopening or a late comment is seen within that many passes (10 minutes), and a restart does not read all
        of them at once. A closed pull request that is not merged is not finished (it can be reopened and merged inside the window, which must be a pr_merged),
        nor is an anchor with no saved state (read now and seeded). One saved before `merged` was kept (state without it) is read as an issue only, once, to learn it."""
        st = state.get(_anc.anchor_id(a_id) or a_id) or {}
        if st.get("state") != "closed": return "full"
        if "merged" not in st: return "issue"
        if not (st["merged"] or not st["pr"]): return "full"
        return "full" if (passno + zlib.crc32(a_id.encode())) % FINISHED_EVERY == 0 else "skip"
    def watch(a_id, with_ci=True):
        """One look at an issue or pull request anchor: its CI (unless `with_ci` is off), then the issue itself (state, comments)."""
        repo, n = split(a_id)
        if with_ci:
            try: ci(a_id, repo, n)
            except Exception as e: log.warning("github ci %s: %s", a_id, str(e)[:120])
        try:
            i = gh(f"/repos/{repo}/issues/{n}", conditional=True)
            if i is None: return                         # 304: nothing changed
            learn(repo, i.get("repository"))
            st = state.get(a_id)
            if st is None: state[a_id] = snap(i); return
            if (i["state"], i["comments"], i["updated_at"]) != (st["state"], st["comments"], st["updated"]): resolved.pop(a_id, None)      # the saved label of a finished anchor is made again at the next start
            title = f"{repo.split('/')[1]}#{n} \"{i['title'][:50]}\""
            if i["comments"] > st["comments"]:
                for c in gh(f"/repos/{repo}/issues/{n}/comments?since={st['updated']}&per_page=20"):
                    if c["user"]["login"] == me and not os.environ.get("ANCHOR_HUB_ALLOW_SELF"): continue
                    # `since` is inclusive of the seed instant, so the comment that set the seeded updated_at
                    # comes back on the next change (an old comment would come back as new): only
                    # comments created after the last observed state are new
                    if _ts(c.get("created_at")) <= _ts(st.get("updated")): continue
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
            etags.pop(f"/repos/{repo}/issues/{n}", None)         # a read that failed after the issue's 200 (the comments, refused by the cap or GitHub) is made again next pass, not answered 304
            if "rate limit" in str(e).lower() or "403" in str(e): hub.hold("github", BACKOFF); time.sleep(BACKOFF)
    hub.hold("github", FIRST_PASS)                         # the first pass after a start reads every anchor: the board counts no age until it ends or this time is up
    hub.gh_state = {"ci": ci_st, "state": state, "etags": etags, "news": thread_news, "committed": committed, "resolved": resolved}      # for inspection and tests
    capped_now = [False]                                                # the cap warning is logged when the state changes, not every pass
    passes = [0]                                                        # polls made since the receiver started (the finished anchors' turn is counted by it)
    def one_pass():
        with hub.lock: ids = [k for k in hub.bindings if k.startswith("github:")]
        skipped = False
        for a_id in ids:
            if held() > 0:                                          # the hourly read cap is spent: the rest of this pass reads nothing; the next pass looks again
                skipped = True; break
            adopt(state, a_id); adopt(ci_st, a_id)           # before release, notifications, ci and the issue read look at either
            touched.clear()
            if a_id.endswith("@releases"): release(a_id)
            elif a_id.endswith("@notifications"): notifications(a_id)   # CI: GitHub's own ci_activity
            elif (mode := how(a_id, passes[0])) != "skip": watch(a_id, with_ci=mode == "full")
            settle(a_id)
        passes[0] += 1
        if skipped:                                                 # a pass the cap cut short is not a finished check
            msg = f"reads held by the hourly cap, resume in {_gb.held_words(held())}"
            if not capped_now[0]: log.warning("github: %s; this pass is cut short", msg)
            capped_now[0] = True; hub.health("github", False, msg)
        else:
            if capped_now[0]: log.info("github: the hourly cap on reads has room again; polling resumes")
            capped_now[0] = False
            with hub.lock: hub.status.setdefault("github", {})["last_pass"] = time.time()
            hub.health("github", True)                              # a finished poll pass is GitHub's real check
    def loop():
        # A pass that raises (a status file that could not be written, a bug) is logged and the next pass runs: the poll thread never ends on one.
        # The pause is on the dot: every poll fires at :00 s (conditional GETs: unchanged issues cost nothing); time.sleep is looked up at each call.
        guarded_loop(hub, "github", one_pass, every=lambda: GHPOLL - time.time() % GHPOLL, retry=GHPOLL, sleep=lambda s: time.sleep(s))
    threading.Thread(target=loop, daemon=True).start()
