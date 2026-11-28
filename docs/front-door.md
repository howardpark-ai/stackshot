# The front door

What this page covers: the front door, one MCP endpoint over several boards and a brain for people who sign in through a reverse proxy: how it is run, the sign-in service the proxy asks, inviting a person, its units, the splitter, releases, who the caller is, the one tool set and its `board` argument, every refusal text, the credential each backend is called with, the instructions text, the health route and what is checked. Back to the [README](../README.md).

The front door is a separate program (`python -m stackshot.frontdoor`, package `stackshot/frontdoor/`). The board server does not import it and does not read its settings. `./install.sh units` renders a unit for each part the config has a table for, and nothing enables or starts one: a person does ([Units, the splitter and releases](#units-the-splitter-and-releases)). A board takes part in it only when its own config says so (see [A board behind the front door](#a-board-behind-the-front-door)); a board with no such table behaves as it always did.

## Run it

```
uv run --project <checkout> --locked --extra server python -m stackshot.frontdoor            # serve
uv run --project <checkout> --locked --extra server python -m stackshot.frontdoor --check    # read the settings, print what would run, exit
```

It needs the `server` extra (FastMCP is already in it, so there is no new dependency). The settings are the `[frontdoor]` table and one `[[frontdoor.backends]]` table per backend of the config file ([Configuration: integrations](configuration-integrations.md), `frontdoor.*`). It does not start (exit 2, the reason on standard error, never a secret) without an `identity_header`, a `members_file` and one usable backend. `--check` also reads the files serving needs: a signing secret, a members file or a backend's credential file that is missing, unreadable or not usable is exit 2, with each one named and no value shown. A backend entry that is wrong is left out, named in the config notes (`stackshot doctor` prints them), and the others are served.

## Who is calling

A reverse proxy in front of it checks the sign-in (for example Caddy's `forward_auth`) and sets one header, named by `identity_header`, to the caller's identity. The front door trusts that header and nothing else: a request to `/mcp` without it is refused with HTTP 401, and `/healthz` is open. The header is plain text: the front door cannot tell a header the proxy set from one a client sent, so the setup has two requirements. First, only the proxy may reach the front door: it listens on the loopback address by default (`listen_host`; any other address is named in the config notes, not refused, and keeping everything but the proxy away is then the setup's job). Second, the proxy must drop or overwrite any copy of that header the client sends itself (with `forward_auth` that is the step that copies the header from the sign-in answer). The signature described below covers only the hop from the front door to a backend; nothing signs the hop from the proxy to the front door. The caller's own `Authorization`, `X-Api-Key` and `Cookie` headers stop at the front door: each backend is called through a transport that sets that backend's headers itself (`forward_incoming_headers=False`).

`members_file` is a JSON object `{"alice": ["main", "side"], "bob": ["main", "brain"]}`: a member and the names of the backends the member is on. It is read at each request. A file that cannot be read makes nobody a member, never everybody.

A member's value may also be an object, for a person who signs in with several addresses or is stored under a name: `{"Pat": {"boards": ["main"], "aliases": ["PJ"], "emails": ["pat@example.com", "pat@example.org"]}}`. The key is the member's identity (the name the proxy sets the identity header to, and the name a board stores the person under); `boards` is the list above; `aliases` are the other names a line of a board's `next` may open with; `emails` are the member's sign-in addresses, kept in lower case, each with an `@`. A key written like an address and given no `emails` is its own address, and in the list form the key is the address as written, so every older file reads as before. No name or address belongs to two members. A name is compared as a board looks it up (without regard to case, surrounding and repeated spaces aside); anything with an `@` is compared without regard to case and surrounding spaces only, so two distinct addresses are never made one. Two keys that differ only in case or in surrounding or repeated spaces (for a key with an `@`: only in case or surrounding spaces) are one person wherever they are listed: a board reads only the first of them, with its boards, aliases and addresses, so list one key with all its boards. Keys come first, then, in the file's order, an alias or address that another member's key or an earlier member already has is dropped from the later one. An entry on no board (an empty `boards`, or an empty list) comes after every member who is on one: it takes no alias or address from them, whether by its key or by its lists. The board's log says each thing that is dropped, a blank alias or address or one that is no text included. A key must be printable ASCII (U+0020 to U+007E) for its member to sign in through the front door, because the headers the identity travels in cannot carry anything else: write an ASCII key and put the other spelling in `aliases`. A key with another character is still read as written, and the board's log warns about it. A call the front door signs is matched to a member by the key alone, exactly. A board that reads its members from this file knows the person by the key, the aliases and all the addresses: any of the addresses signs in as that person, and a call the front door signs for the key is that person's. A sign-in service finds the member of a verified address with `frontdoor_files.member_of_address`. A value that is neither a list nor an object is a member of nothing.

## What a backend is called with

The front door's own credential, never the caller's: `Authorization: Bearer <the token in token_file>`, or an OAuth access token the front door asks for with the client credentials in `client_id_file` and `client_secret_file` and the `scopes` listed. A secret file is read as a brain's `secret_file` is: a regular file private to its owner, at most 64 KiB, a printable value of 16 characters or more; nothing it holds is printed or logged.

The caller's identity goes to the backend as a second header, `x-stackshot-identity`, signed: `v1.<identity>.<time>.<HMAC-SHA256>` under the secret in `identity_secret_file` (`stackshot/core/frontdoor_identity.py`, `sign` and `verify`, shared by the front door and the boards: a value that is altered, signed with another secret, older than five minutes or dated ahead of the clock does not verify). A board that is told so by its config checks it (next section); the front door signs it for each connection it opens to a backend.

## A board behind the front door

A board is told it sits behind a front door by a `[behind_frontdoor]` table in its own config ([Configuration: integrations](configuration-integrations.md), `behind_frontdoor.*`). With no such table nothing here applies: the board serves every call as before and its members are the ones it always had. The table does two things, each by its own key, and neither needs the other.

**It checks the signed identity** (`identity_secret_file`). Every request to the board's MCP path must carry the `x-stackshot-identity` header, and the value must verify under the secret in that file and inside the replay window (`identity_max_age_seconds`, 300 by default, 1 to 3600). The board reads the secret at each call, so a rotated secret applies to the next one. A request that fails is refused with HTTP 403 and one plain-text sentence, and goes no further:

| When | Text |
| --- | --- |
| no signed identity on the call | `refused: this board takes calls through its front door only, and this call carries no signed identity.` |
| the identity is altered, signed with another secret, older than the window or dated more than 30 s ahead of the board's clock | `refused: the signed identity of this call is not accepted (it is altered, signed with another secret, older than this board's replay window, or dated ahead of its clock).` |
| the board cannot read the secret (missing, readable by group or others, too short) | `refused: this board cannot read the secret that checks a signed identity, so it accepts no call until that is fixed (the board's log says why).` |

The status is 403, never 401: a front door whose credential for this board is an OAuth client would take a 401 as an expired token and ask for a new one. The text says nothing about which part was wrong and never holds a secret or a path. Only the MCP path is checked: the board's pages, its client API, its sign-in and its health route are as they were, because the front door's health check is an open route. The identity the check verified is the caller of everything in that request: the board asks for it before a list, a read or a call, and a request that did not pass the check has none and is refused. Whatever the board's sign-in mode, behind a front door the caller is the signed identity, and a caller the board's members do not list gets `Refused: <identity> is not allowed on this board` for every list, read and call (a call as a tool error, any other request as a JSON-RPC error with code -32003) and no instructions text ([The board, the publisher and the connector](board-and-connector.md)).

The bearer the front door calls with is the board's own sign-in, as for any other client; the signed identity adds who the call is for. Keep the secret file private to its owner (mode 600): a board whose file group or others can read does not use it, and says so in the config notes and the log.

**What a captured identity header lets its holder do.** The signature covers the identity and the time it was signed, and nothing else: it is not bound to a method, a path or a body. Anyone who gets hold of one signed header (from a log, a proxy in the middle, a packet capture) can send it with any request of their own and act as that identity on that board, until it is older than `identity_max_age_seconds` (300 s by default); inside that window the board cannot tell the replay from the front door's own call, and a shorter window narrows the exposure but does not close it. The signed header proves that the front door vouched for the identity a moment ago, not that this request is the one it vouched for. So keep the hop from the front door to the board on the loopback address or on a private link (a private network or a tunnel between the two machines), and send the header over TLS where the hop crosses a network anyone else can read. The board itself does not check where a call comes from: its own listen address and the path the call takes to it are the deployment's to keep closed, and the board's checks (the signed identity, the bearer of its own sign-in, the members' list) all assume a hop only the front door can use.

The front door signs per connection, when it opens its client to a backend, so a call that goes on for longer than the replay window can have the follow-up requests of that connection (a cancel, the end of the session) refused. A deployment with tools that run for minutes raises `identity_max_age_seconds`; signing per request is not part of this stage.

**It reads its members from the front door** (`members_file` and `board_name`): the board's list of people is the identities the front door's members file lists for this board's name, read at each call (one source; a change of the file applies to the next call, an open session included). The file's format is the front door's own, `{member: [backends]}`: `{"alice": ["main", "side"], "bob": ["side"]}` makes `alice` a member of the boards named `main` and `side` and `bob` of `side`. A probe's layout is the other way round (board to members, listing for each board who is on it); the board here reads the file for its own name and keeps the members whose list holds that name, in the file's order. Each identity is both the person's name on the board and the one sign-in address that matches (as written: another case is another address). Two identities of the file that differ only in case or spacing (`Alice@x` and `alice@x`, `Bob Lee` and `bob  lee`) would be two identities but one name, because a board's names are unique without regard to case and repeated spaces; the first of them in the file is the member, the later one is left out, and the log says so once. A file that cannot be read, is no JSON object, is over 64 KiB, or lists nobody for this board leaves the board with nobody (never everybody), and the log says why once. While `members_file` is set, the board's `[[members]]`, `[instance] owner` and `[auth] allowed_emails` say nothing about who is a member or who may sign in, and the config notes say so when a `[[members]]` list is still there. There is one exception, for names alone: on a machine where no file at all is at the `members_file` path (one that only reads the board's text), a line of text and a mover's name are read against `[instance] owner` and `owner_aliases`, so the owner's steps are still recognized. A file that is there and cannot be read or is not valid is not absent.

The board's server needs no front door code: both sides share `stackshot/core/frontdoor_identity.py` (sign and verify) and `stackshot/core/frontdoor_files.py` (the secret and the members file), which `stackshot/frontdoor/identity.py` and `stackshot/frontdoor/config.py` still name. A table that is present but wrong is never read as absent: a board told to check identities that cannot read its secret refuses every call, and a board told to read its members that cannot has nobody. The config notes (`stackshot doctor`) name what is wrong. The table is restart-only, and the secret and the members file are read at each call.

When a board refuses a call, the front door shows it the way it shows any backend that does not answer: `board '<b>' did not answer (error: ...)` on a call and `board '<b>' did not list its tools (...)` on a list, with the status in the front door's log, so a board with the wrong secret is told from one that is down by `/healthz`, which stays open.

## The token check for the sign-in service

A reverse proxy asks a sign-in service who a connector's bearer token is for before it lets the call reach the front door. The service holds neither the board's Google client nor a copy of the board's token store: it asks the board, which already checks its own tokens. A board offers that check with `verify_secret_file` in its `[behind_frontdoor]` table; the key works alone (a board can offer the check before it takes calls through the door only), and without it the board has no such route.

`GET /frontdoor/verify` answers a request that carries two things: the sign-in service's signed header, `x-stackshot-verify` (the same signing as the signed identity, `frontdoor_identity.sign`, under the secret in `verify_secret_file`, of the fixed word `token-check`, with the same replay window), and the caller's `Authorization: Bearer <token>`, read as the board's MCP path reads it (`Bearer ` in any case, and everything after that one space is the token). The route is reachable wherever the board is (the tunnel and the proxy deliver to one address), so the signed header is the gate and the address is not: a request without a valid header is refused 403 with a sentence, and the route says nothing about its token. The token is still read on such a request: FastMCP's bearer middleware wraps every route of the app and calls the board's `verify_token` on any bearer before a route runs. The proxy in front of the board also blocks the path to everything from outside.

| When | Answer |
| --- | --- |
| no header, an altered one, another secret, older than the window, dated ahead | 403 `refused: ...` (a sentence that names neither secret) |
| the board cannot read the verify secret | 403 `refused: this board cannot read the secret that checks the sign-in service's header...` |
| a correctly signed header, and the verify secret is the same as the identity secret | 403 `refused: this board's secret for the sign-in service's header is the same as its identity secret...` |
| a token the board's sign-in accepts | 200 `{"email": "<lower case>", "via": "google"}`, or `"via": "portal"` for the portal's machine token |
| a token the board's sign-in accepts, of a Google sign-in a registration refuses ([Inviting a person](#inviting-a-person)) | 403 `{"error": "not_admitted", "why": "<reason>", "email": "<lower case>"}` |
| no bearer, an empty one, not `Bearer`, a token the board does not know, expired or revoked, or one with no address | 401 `{"error": "invalid_token"}`, with the `WWW-Authenticate` header below |
| the check itself raised | 503 `{"error": "unavailable"}`, never 401 |
| the board has no sign-in (`[auth] mode` off) | 404 |

The check is the board's own `verify_token`, the call its browser sign-in makes: the token's signature, the stored mapping, and Google's own check of the grant at every call, so a grant revoked at Google is refused at once. What the library swallows (a network failure reads as "no such token") arrives as 401, as it does for a direct call to the board. Every answer is `Cache-Control: no-store`, and no answer holds the token.

A 401 carries the `WWW-Authenticate` value the board's own `/mcp` sends for the same request: with no `Authorization` header the challenge names no error, with one it says `error="invalid_token"`, and both name the `resource_metadata` address a connector discovers the sign-in by (and the scopes to ask for). The board takes the value from the library's own guard on `/mcp`, so it follows the board's `[auth] base_url` and MCP path. A sign-in service that passes it on gives a connector the same sign-in discovery as the board. No other answer (403, 404, 503, 200) carries the header.

**What the sign-in service can rely on.** A 200 says the token is valid and no registration refuses it, not that the account is a member of any board: the sign-in service checks membership. The service treats any 5xx as a refusal. The signed header is bound to neither the token nor the request, so whoever gets hold of one can send it again, with any token, until it is older than `identity_max_age_seconds`: keep that hop as private as the one the signed identity takes. The verify secret and the identity secret must differ, because the service holds the verify secret and with the identity secret it could sign a call as any member: a board that checks identities and whose two files hold the same value answers no check, and its log says why.

## The sign-in service

`python -m stackshot.frontdoor.signin` (`stackshot/frontdoor/signin.py`) is the program the proxy's `forward_auth` asks about each request. It is a program of its own and listens on 127.0.0.1 only; `./install.sh units` renders its unit when the config has its table, and nothing enables or starts it.

```
uv run --project <checkout> --locked --extra server python -m stackshot.frontdoor.signin            # serve
uv run --project <checkout> --locked --extra server python -m stackshot.frontdoor.signin --check    # read the settings, print what would run, exit
```

The settings are the `[frontdoor_signin]` table ([Configuration: integrations](configuration-integrations.md), `frontdoor_signin.*`). `--check` also loads everything serving needs, so it fails where the `server` extra is not installed. The service does not start (exit 2, the reason on standard error, never a secret) without a `board_verify_url`, a `verify_secret_file`, a `members_file` (its own, or the one of `[frontdoor]`) and an `identity_secret_file` (its own, the one of `[frontdoor]` or the one of `[behind_frontdoor]`). A service asks one board, and the tokens it accepts are the tokens that board accepts.

The verify secret is a secret of its own. The service does not start when it is the same file as an identity secret its config names (`frontdoor_signin`, `frontdoor` or `behind_frontdoor` `identity_secret_file`, links resolved) or holds the same value, nor when it cannot read one of them: whoever holds the identity secret can sign any caller's identity to a board. The comparison is made at the start; restart the service after changing either secret.

The verify secret has to be the same value as the board's (`[behind_frontdoor] verify_secret_file`, which may name the same file). Where the board the service asks is the one of its own config (a loopback `board_verify_url` on `[server] port`), `--check` compares the two and exits 2 when they do not match, showing neither; its line says when it could not compare.

### Caddy in front

Use Caddy 2.11.8 or later. What the earlier releases lack:

- Before 2.11.2, `copy_headers` could leave a client's own identity header in place when the check's answer did not carry it ([GHSA-7r4p-vjf4-gxv4](https://github.com/caddyserver/caddy/security/advisories/GHSA-7r4p-vjf4-gxv4)).
- Before 2.11.6, `forward_auth` beside `reverse_proxy` could send a request over a connection made for the wrong upstream ([GHSA-6365-7ppr-5r92](https://github.com/caddyserver/caddy/security/advisories/GHSA-6365-7ppr-5r92)). The advisory names 2.11.5, which has no release to install (the tag has none).
- 2.11.6 cuts off a streamed answer to a request with a body, an MCP call's event stream among them, 60 seconds after the body was read ([2.11.7 fixed it](https://github.com/caddyserver/caddy/releases/tag/v2.11.7)).
- 2.11.8 completes the fix for connection headers of an upstream that the proxy passed on to the client, in interim (1xx) answers too ([GHSA-8qx7-j2v2-x6q5](https://github.com/caddyserver/caddy/security/advisories/GHSA-8qx7-j2v2-x6q5)), and it is the first release that refuses a `Host` holding dot segments or slashes ([GHSA-r766-rf9f-588h](https://github.com/caddyserver/caddy/security/advisories/GHSA-r766-rf9f-588h)).

For a front door on port 8020 whose `identity_header` is `x-forwarded-user`, a service on port 8021 and the board that service asks on port 8010:

```
mcp.example.com {
	# The board's own sign-in, which a connector uses before it has a token, and the setup page an invite links to. The match is
	# on the request line as it arrived: a `path` matcher would ignore case and tidy the path before comparing, and the board does neither.
	@signin vars_regexp {http.request.orig_uri} ^/(\.well-known(/[A-Za-z0-9_-][A-Za-z0-9._-]*)+|authorize|token|register|consent|auth/callback|join)(\?.*)?$
	route {
		request_header -X-Forwarded-User
		reverse_proxy @signin 127.0.0.1:8010
		forward_auth 127.0.0.1:8021 {
			uri /verify
			copy_headers X-Verified-User>X-Forwarded-User
		}
		reverse_proxy 127.0.0.1:8020
	}
}
```

- `route` keeps the lines in the order written. Outside it, Caddy's own order runs `forward_auth` before `request_header`, which would remove the identity the check had just set.
- `request_header -X-Forwarded-User` removes a client's own identity header before anything else. It names the front door's `identity_header`, as `copy_headers` does.
- Seven kinds of path go to the board unchecked, and no others: `/.well-known/...` (the discovery documents), `/authorize`, `/token`, `/register`, `/consent`, `/auth/callback` and `/join`, the setup page of [Inviting a person](#inviting-a-person) (a board without `[invites]` has no such page). Everything else goes through the check to the front door, `/mcp` included, and so does one of these paths written another way (another case, an encoded character, a dot segment, a doubled or trailing slash): it needs a token like any other.
- On the board the service asks, `[auth] base_url` is the public address (`https://mcp.example.com` here), so that the metadata's `resource` and the `resource_metadata` of a 401 name the URL a connector uses. The board's Google OAuth client lists `https://mcp.example.com/auth/callback` as a redirect URI.
- The board's own browser sign-in (`[auth] ui_open = false`) is built on `base_url` too and ends at `/ui/callback`, which this block does not send to the board, so with `base_url` at the front door's address that sign-in does not work.

### What it answers

`GET /verify` reads one thing of the request, the caller's `Authorization: Bearer <token>`. It sends that token to the board's [token check](#the-token-check-for-the-sign-in-service) with the signed header `x-stackshot-verify`, and answers by what the board says:

| When | Answer |
| --- | --- |
| the board answers 200 with an address and the kind of token, `"via": "google"` (or `"portal"` with `accept_portal_token` on) | 200, no body, `X-Verified-User: <identity>`: the key of the member whose sign-in addresses hold the address (compared in lower case), or the address in lower case when no member holds it |
| the board answers 200 with `"via": "portal"`, its machine token, and `accept_portal_token` is not on | 403 with a sentence and no identity header |
| the board answers 200, no member's sign-in addresses hold the address, and the members file has a key written exactly as that address | 403 with a sentence and no identity header: the front door matches keys exactly and would take the caller for that member. Add the address to that member's `emails` when it is theirs |
| the board answers 401: no bearer (the token follows `Bearer` and exactly one space, as the board reads it), another scheme, a token it does not know, expired or revoked | 401 `{"error": "invalid_token"}`, with the board's `WWW-Authenticate` text word for word ([the token check](#the-token-check-for-the-sign-in-service) sends the challenge of the board's own `/mcp`). The service writes none of its own |
| the board answers 403 `{"error": "not_admitted", ...}` with a reason the service knows and an address, to a check that carries a token | 200, no body, `X-Verified-User: !refused:<reason>:<address>`: an identity that is a member of nothing, so that the front door tells the caller which address signed in and why it is not let in |
| anything else: any other 403 of the board (the two secrets differ), 404 (a board with no sign-in), 5xx, a redirect, an answer that names no ASCII address or no kind of token, no whole answer in `timeout_seconds`, a board that cannot be reached; a secret or members file that cannot be read; a member the file lists under two keys that differ only in surrounding spaces, with different boards (a board reads the first entry, the front door the last); an identity that is not printable ASCII; a fault of the service | 503 with a sentence and no identity header. Never 200, and never 401: a 401 tells a connector that its token is no good |

A board's 200 says who the token is for, never that the person is a member: the service decides that from the members file. A person no member holds is not refused here (but for the 403 case above): the front door answers `you are not a member of any board.` and names the address that signed in. A member's key goes into a header as it is, so a member who signs in through this service has a key of printable ASCII characters.

**The board's machine token.** The token a board takes as `[auth] portal_identity` (what a portal in front of the board, or a script, holds) passes the board's token check too, which says `"via": "portal"`. The service refuses it unless `[frontdoor_signin]` has `accept_portal_token = true`: that token belongs to one board, and as its person's identity at the front door it reaches every board that person is a member of. Switch it on only where whoever holds the token may use all of those boards: add the line and restart the service. `--check` says whether it is accepted.

A 200 of the board that the service accepts, for an address a member holds, is reused for `cache_seconds` (5 by default, 0 turns it off), under a SHA-256 of the token, at most 1024 of them. Nothing else is kept, so a token the board refused, a refused registration included, is asked about again at the next request, as is one whose address no member holds (an address registered a moment later is checked at its next request), and a token revoked at the board keeps working through the service for at most that long. The secret and the members file are read at each request, cached or not.

The service reaches the board directly, whatever proxy the environment names, follows no redirect and keeps no cookie. It holds at most 64 connections to the board; a further check waits for one within its own `timeout_seconds`.

Every answer is `Cache-Control: no-store`. A header the client sends is not repeated in the answer, whatever its name. The log names a request by the first 8 hex digits of a hash of the token and of the identity; no token, secret or address is written to it. It keeps no access log and speaks no websocket protocol (a websocket upgrade is answered as the plain request it also is): Caddy's check carries the query string of the caller's own request, which the service neither reads nor writes. `GET /healthz` answers 200 `{"status": "ok"}` when the secret and the members file can be read and 503 `{"status": "degraded"}` when not; it does not ask the board.

## Inviting a person

A board's admin lets a person in by their Google address, through the admin's own AI agent. All of it is off (no `invite` tool, no `/join` page, no further redirect URI) until the board's config has `[invites]` ([Configuration: integrations](configuration-integrations.md), `invites.*`; restart-only):

```
[invites]
admins = ["alice"]      # members, by their names in the members file
```

It goes in the config of the board the sign-in service asks, which is the sign-in server, and needs there `[auth] mode = "google"` with an https `base_url`, and `[behind_frontdoor]` with `members_file`, `board_name` and `verify_secret_file`. While one is missing the tool refuses and says which, and so do the config notes. To invite through the front door, as in the steps below, the board needs `identity_secret_file` as well ([A board behind the front door](#a-board-behind-the-front-door)), which `[invites]` does not check: without it the board takes a call from the front door as the account of the door's own credential, so the admin is not known there. A machine token is then refused, and a credential that is an admin's own sign-in would let everybody the door lets through invite. The user the board runs as has to be able to write the members file and its directory: a change is a new file renamed over the old one (the mode kept, a link followed), made under a lock on `<members file>.lock`, which stays beside it. A change is refused, and the file left as it was, when the file writes a name twice (writing it again would drop one), when it would pass 64 KiB, and on a read-only standby.

### The steps

1. The admin asks their agent to add an address, and the agent calls `invite(address="new@example.com")`. The server checks that the caller is signed in as a member `admins` names, registers the address on this board and answers with the setup link (`<base_url>/join`) and an invite mail, subject and body, in the language the admin reads the board in. The board sends no mail: the agent drafts it with its own mail connector, and it goes when the admin sends it.
2. The newcomer gives the link to their own AI agent. The page says how to add the board's MCP address (`mcp_url`) in claude.ai, Claude Code, ChatGPT and Cursor, for the agent to do or to tell the person.
3. The person signs in with Google and allows. A newcomer gets in only once their address is registered ([who reads and writes](#who-reads-and-writes)).
4. Once connected, the connector's instructions tell the agent how to walk a newcomer through the first use. Nothing is made for them at joining: no board and no brain of their own.

### The registration

The board writes one entry of the members file, which the front door, the sign-in service and the board read as any other member:

```json
"new@example.com": {"boards": ["main"], "emails": ["new@example.com"],
                    "invited": {"by": "alice", "at": "2027-01-02T10:00:00+09:00", "google_sub": ""}}
```

For an entry with `invited` the board asks two things more of each Google sign-in: that Google reports the address as verified, and that the account is the one the entry has recorded. The first verified sign-in records the account's id in `google_sub`. The board asks this of a sign-in to its own connector at every list, read and call and before it gives the instructions text, at its browser sign-in and the session that made, and at the [token check](#the-token-check-for-the-sign-in-service), which is where a sign-in that comes through the front door is asked. It asks for every invited entry of the file, with `[invites]` or without. While `[auth] ui_open` is true (the default) the board's web pages ask for no sign-in, so neither a registration nor its removal decides who reads or uses them: that is for whatever stands in front of those pages. An entry written by hand is asked neither, and the tool changes none: an address that any such entry already holds, as a key, an alias or a sign-in address, is not registered a second time. Registering an address another board registered adds this board to its entry.

| Reason | What the person reads after their address |
| --- | --- |
| `unverified` | `Google does not report this address as verified.` |
| `other_account` | `This address first joined with another Google account. An admin can remove the registration, on every board it is on, and make it again.` |
| `unrecorded` | `The first sign-in could not be recorded, so nothing is let in yet. Try again, or ask the person who invited you.` |
| `unreadable` | `The board cannot check this address's registration now. Try again, or ask the person who invited you.` |

Through the front door these follow `you are not a member of any board. <address> signed in and is not let in.`; the board's own connector answers every list, read and call with `Refused: <address> is not let in.` (a call as a tool error, any other request as a JSON-RPC error with code -32003) and gives no instructions text; the browser sign-in answers `<address> is not let in.`; each with the reason. A sign-in service older than the board takes such an answer for an outage and lets nobody in.

### Who reads and writes

What a signed-in person gets from the connector. Reading is the instructions text, the lists (tools, resources, resource templates, prompts), every read, the rulebook included, and every tool that reads; writing is every tool that changes something.

| Signed in as | Reads and writes |
| --- | --- |
| an address no member holds: a stranger, or a person not yet added | nothing: no read and no write, and no text of a board's instructions |
| a registered address, from a Google account the registration accepts | what any member of the board does; `invite` is refused unless `admins` names them |
| a registered address that Google does not report as verified, or from another account than the recorded one | nothing, and the refusal says which address signed in and why |
| a removed person, or a member taken off the board in the members file | nothing of that board, from their next request on, in an open session too |

The refusals are worded in [The refusals](#the-refusals) and under [The registration](#the-registration). To someone it does not let in, a board's own connector refuses every list, read and call, and still answers the start of a session (`initialize`, `server/discover`), with no instructions text, and a `ping`. The front door refuses such a person the tool list and every call; it serves tools only, so to anyone its resource and prompt lists are empty and a read of one finds nothing. Through it, a person the members file puts on no backend gets the door's own `preface` and no backend's text. The board's web pages are not part of this table (`ui_open`, above).

### Taking it back

`invite(address="new@example.com", remove=true)` takes this board off the registration and deletes an entry left on no board. The members file is read at each request, so from the person's next request on, they get no list, read, call or instructions text of this board through a connector, with sign-in tokens already issued too, unless an entry written by hand still lets the address in (the tool's answer says so). Through the front door, a person the members file still puts on another board goes on using that one. Machine tokens and enrolled keys are not part of a registration and are revoked separately; the tool's answer says so. Neither are the web pages of a board whose `ui_open` is true (above). The recorded Google account stays with the entry while any board is on it, so removing one board of several and registering it again keeps the account. To let another account join, an admin of every board the entry lists removes it, or `google_sub` is set to `""` in the file; then register it again where it was removed. An admin's own entry is not removed (take the name out of `admins` first), and a hand-written entry is changed in the file. An address removed and registered again within the sign-in service's `cache_seconds` (5 by default) of the old account's last call can be passed for the rest of those seconds without the account being asked.

### Who may invite

A member `admins` names, signed in with their own Google account. A board called directly refuses its machine token. Behind the front door, with `identity_secret_file`, the board sees the identity the door signed and not which token the caller held: the sign-in service refuses the machine token unless `accept_portal_token` is on, and with it on, whoever holds the token invites as its member where that member is an admin (the config notes say so).

### The setup page

`GET /join` is open to anyone. It holds the connector's address and the same words for everyone: no secret, member, item or board name, and nothing about whether an address is registered. It is in a signed-in reader's language, else English, carries no script and loads nothing. It answers 60 requests a minute from one source and 600 from all together, then 429 with `Retry-After`. The source is the connection's address as the board's server reads it: the peer, or the client that a proxy on the loopback address names in `X-Forwarded-For` (a proxy there that names none makes every reader one source). An IPv6 address counts by its /64, an IPv4-mapped one as the IPv4 address it carries. The proxy in front has to send the path to the board with no token ([Caddy in front](#caddy-in-front); the [splitter](#the-splitter) already does).

### The apps' redirect URIs

While `[invites]` is on, these are accepted beside `[auth] allowed_client_redirect_uris` and the board's own callback. Scheme, host and path have to match, the path to the letter and the host in any case. A loopback entry written with no port takes any port ([RFC 8252](https://www.rfc-editor.org/rfc/rfc8252#section-7.3), 7.3). An entry written with a port takes that port only, but `http://localhost/callback` has none, so while it is in the list `/callback` on `localhost` is taken on every port, Cursor's 8787 among them. An entry for another host takes the scheme's default port, written out (`:443`) or not. The sign-in library compares nothing else, so a URI with an added query, `;parameters` or `#fragment` is accepted too, for these entries and for claude.ai's. The code is still sent only to a listed host and path.

| App | Redirect URI | Where the app says so |
| --- | --- | --- |
| ChatGPT | `https://chatgpt.com/connector_platform_oauth_redirect` | [Apps SDK, authentication](https://developers.openai.com/apps-sdk/build/auth), [its client metadata](https://chatgpt.com/oauth/client.json) |
| Claude Code | `http://localhost/callback`, `http://127.0.0.1/callback` | [its client metadata](https://claude.ai/oauth/claude-code-client-metadata), [MCP in Claude Code](https://code.claude.com/docs/en/mcp) |
| Cursor | `http://localhost:8787/callback`, `https://www.cursor.com/agents/mcp/oauth/callback` | [Cursor, MCP](https://cursor.com/docs/mcp) |

claude.ai's callback is in the default of `allowed_client_redirect_uris`. ChatGPT's callback of the form `https://chatgpt.com/connector/oauth/<id>`, with an id of its own for each connector, is not added, since taking it would need a wildcard in the path: where an app asks for one, add that exact URI to `allowed_client_redirect_uris`.

## Units, the splitter and releases

### The units

`./install.sh units` renders a user unit for each part of the front door whose table the config has. A config without the tables installs exactly what it installed before.

| Unit | Rendered when | What it runs |
| --- | --- | --- |
| `stackshot-frontdoor.service` | `[frontdoor]` | the front door |
| `stackshot-signin.service` | `[frontdoor_signin]` | the sign-in service |
| `stackshot-splitter.service`, with `~/.config/stackshot/splitter.Caddyfile` | `[frontdoor_splitter]`, `[frontdoor]` with an identity header and `[frontdoor_signin]`, and a `listen_port` that `[server] port` does not give the board | the splitter, a Caddy on 127.0.0.1 |

Nothing here turns one on: not `setup`, not `./install.sh units` with or without `--start`, not a release. A person does it once, with `systemctl --user enable --now <unit>` (a release restarts a front door or sign-in unit that is turned on, which starts an enabled one that is stopped: [Releases](#releases)). With `--restart` or `--start`, `install.sh` restarts a front door unit whose file changed only when it runs already. A unit an earlier run installed is not removed when its table goes.

The front door and the sign-in service are `PartOf=stackshot.service`: a restart of the board restarts them and a stop of the board stops them. Once enabled they are also wanted by the board, so starting it starts them.

### The splitter

The splitter takes the address the board's clients already use. It sends the MCP path (`/mcp`) through the sign-in service's check to the front door and everything else to the board. Before anything reads a request it removes the identity headers a client sends; it answers the board's token check (`/frontdoor/*`) with 404; its admin API is off; it trusts `X-Forwarded-*` from the loopback address only; and it listens on 127.0.0.1 only. It needs Caddy 2.11.8 or later ([why](#caddy-in-front)) at `[frontdoor_splitter] caddy` (`/usr/bin/caddy` by default).

Moving a board that clients reach on a port behind the splitter, in this order:

1. Give the board another port (`[server] port`). Point at that port everything that asks the board directly: the board's `url` and `health_url` in `[[frontdoor.backends]]`, `[frontdoor_signin] board_verify_url`, and a client on this machine that must not go through the front door. Add the board's `[behind_frontdoor]` table with `verify_secret_file`, which the sign-in service needs. Restart the board.
2. Add `[frontdoor_splitter]` with `listen_port` set to the old port, run `./install.sh units`, and enable the front door and the sign-in service.
3. Enable the splitter: `systemctl --user enable --now stackshot-splitter.service`. From here the old address reaches the splitter.

The splitter cannot take the port while it is the board's. `install.sh` renders no splitter whose `listen_port` is the one `[server] port` gives the board, and the unit checks again before every start, a reboot's included (`ExecStartPre`, `stackshot/frontdoor/splitter.py`): it does not start unless the values it was rendered with are what the config says now, the config still allows a splitter and the Caddy is new enough.

To undo, stop the splitter first:

1. `systemctl --user disable --now stackshot-splitter.service`. The check runs only when the splitter starts, so a splitter that is still running keeps the port, and the board cannot bind it.
2. Give the board its port back (`[server] port`, and the addresses of step 1), restart it, and disable the front door and the sign-in service if they are not to run.

A splitter left enabled after the config gave the port back does not start at the next boot; `systemctl --user --failed` shows it.

Before the server is rolled back to a commit from before the splitter's unit existed, undo the move with the two steps above. Such a rollback takes the module of the splitter's check out of the checkout and leaves the unit installed: a splitter that is running goes on, but from its next start, a reboot's included, the check cannot run, so the splitter does not start and nothing answers at the old address.

### Releases

`deploy.sh` restarts the front door and the sign-in service with the board, where their units are turned on: enabled, or running. A unit that failed and is not enabled is off (`disable --now` leaves the failed state behind), so no release restarts or checks it. It restarts a running splitter only when the splitter's unit or Caddyfile template changed. After the board's health check, with at least one front door unit turned on, the deploy runs

```
uv run --project <checkout> --locked --extra server python -m stackshot.frontdoor.check --installed --wait 90
```

and fails, as it fails on a board that does not answer, when a part does not do its work (a release then reports it and pauses the release queue; nothing is rolled back for a failed deploy). A health route is not enough here: the front door answers its own routes and an MCP initialize with its board down. So the check makes a real tool call (`sessions`, which only reads): through the front door with a member's identity, and through the splitter with the board's machine token. It also asks the sign-in service's token check, and sees that the splitter refuses a client's own identity header and the token check path. With `accept_portal_token` off the machine token is refused through the splitter by design: the check says so and makes no tool call that way. The token checks need to know which board is this machine's: the `[[frontdoor.backends]]` entry whose url is a loopback address on `[server] port`, else the only board listed. Where that cannot be told, the front door is still called on every board listed, the sign-in service and the splitter are checked without a token, and their lines say that the token was not tried. With no board listed, the front door's health route alone is asked. The units are found by the names above; a part run another way is not checked.

The same check by hand, against an address:

```
uv run --project <checkout> --locked --extra server python -m stackshot.frontdoor.check --door http://127.0.0.1:8030 [--as MEMBER] [--board NAME]
uv run --project <checkout> --locked --extra server python -m stackshot.frontdoor.check --signin http://127.0.0.1:8031 [--board NAME]
uv run --project <checkout> --locked --extra server python -m stackshot.frontdoor.check --splitter http://127.0.0.1:8020 [--board NAME]
```

Set `STACKSHOT_CONFIG` to the instance's config. `--door` sends the identity header itself, naming a member of the board; `--splitter` and `--signin` read the board's machine token from the front door's `token_file`. The token is never printed or passed as an argument, and is not sent over plain http to another machine. Exit 0: passed; 1: something did not, and the last line says what; 2: the arguments or the config allow no check.

### After a new machine token

The front door keeps its own copy of the board's machine token (`[[frontdoor.backends]] token_file`). After a new token in `<paths.secrets>/oauth.env`:

1. Restart the board: it reads the file at its start only.
2. At once, copy the token: `stackshot frontdoor-token` (or `uv run --project <checkout> --locked python -m stackshot.frontdoor.boardtoken`), with `--board NAME` when more than one of the front door's boards is on this config's `[server] port`. A board whose url is not a loopback address on that port is refused: the token in this `oauth.env` is this machine's board's. The front door reads its token file at each request, so it needs no restart; between step 1 and this step its calls to the board are refused.
3. Check with a real call: `python -m stackshot.frontdoor.check`, as above.

The command writes a new file, readable by its owner only, and moves it over the old one in one step. It prints no value and takes none as an argument. `--check` says whether the file holds the board's token and writes nothing (exit 0 it does, 1 it does not, 2 it cannot tell). Where releases run, hold them around the steps (next).

### Holding releases

A release restarts the board. While work on the server must not have that in its middle, hold releases:

```
./release.sh hold --minutes 30 --by "<who>" --why "<what for>"
./release.sh hold --status
./release.sh hold --end
```

While the hold stands no release deploys: one started by hand or by the queue still merges its PR, then waits before its deploy, says in its log and in one message who holds and why, and goes on by itself when the hold ends. A rollback waits too. `release.sh queue --list` shows the hold. It ends after the minutes given, 120 at most, or by `--end`. The command first waits for a deploy that is under way. `deploy.sh` run by hand does not look at the hold. Where `release.sh` runs on another machine than the server (`[release] deploy_ssh`), run the hold there.

## The live switch scripts

Four scripts help move a running single-user board behind the front door on its own machine: the board goes from port 8020 to 8021, the splitter takes 8020, the front door listens on 8030 and the sign-in service on 8031. These ports are fixed in the scripts.

Run them on the board's machine with `python3` (3.11 or later) and `STACKSHOT_CONFIG` set to the instance's `stackshot.toml`. None of them asks a question, and none commits or pushes anything. A script that writes is a dry run until it is given `--apply`, and one such run goes at a time (a lock at `~/.config/stackshot/frontdoor-switch.lock`, dropped when its process ends). The config saves, the proxy in front of the machine, and every check in a browser or a client stay a person's work: the scripts print those as `MANUAL` or `OPERATOR` lines.

| Script | What it does |
| --- | --- |
| `tools/frontdoor_preflight.py --backup-dir DIR` | what has to hold before the first step; read-only |
| `tools/frontdoor_snapshot.py --expect MEMBERS,ALIASES,ADDRESSES --apply` | the snapshot, then the front door's secrets and members file |
| `tools/frontdoor_cutover.py --snapshot DIR --apply` | the cut-over as one run, with the way back built in |
| `tools/frontdoor_undo.py --apply` | the way back to the single-user board on 8020; `--saved` runs it on the saved copy whatever the config on disk says; `--drop-saved` removes the saved config of a switch that is kept |

All four use the same exit codes:

| Exit | Meaning |
| --- | --- |
| 0 | passed (a dry run included), nothing left to look at |
| 1 | a check failed or the script refused; this run did not restart the board |
| 2 | the call cannot run as asked |
| 3 | every automated check passed; manual checks are pending |
| 4 | the board is back on 8020 on a saved copy of the config; reverting or fixing the config is still to be done |
| 5 | the way back did not complete: a person is needed now |

`FRONTDOOR_PUBLIC_URL` is the board's public address (`https://...`); `--apply` of the cut-over and of the way back require it. A number of seconds in a `FRONTDOOR_SWITCH_*` variable above 300 is read as 300; one that is not above 0, or no number, is refused.

### Before the cut-over

1. `tools/frontdoor_preflight.py`: the config is a single-user one, the checkout is new enough, no release hold, queue or running release, ports 8021, 8025, 8030 and 8031 are free, the board's, the minute runner's and the portal sync's units are installed, no override of an earlier way back, the config notes can be read (`--baseline FILE` compares them), and the newest file in the backup folder (`--backup-dir` or `FRONTDOOR_BACKUP_DIR`) is of today. What only a person can see is a `MANUAL` line until `--confirm NAME` says it holds. It changes nothing of the board, its config or its units; reading the config notes runs `uv run` in the checkout, which may first sync that checkout's environment.
2. Hold releases ([Holding releases](#holding-releases)).
3. `tools/frontdoor_snapshot.py`: first the member list, before anything is written. `members.json` is the one that is there, else it is made from the members as the board reads them (`[[members]]`, else `[instance] owner` and `owner_aliases` and `[auth] allowed_emails`; sessions listed as a member's `agents` are not carried over). It has to hold `--expect`'s number of members, aliases and addresses, and the front door has to read every entry. A file that is there and stays also has to let each member the config gives reach the board `main`, found by name or sign-in address. Two data folders that would get the same name in the archive, or one inside the other's, are refused. Then a new folder under `FRONTDOOR_SNAPSHOT_ROOT` (default `~/.local/share/stackshot-runs/frontdoor-switch`) with an archive of `[paths] repo` and `state` (or each `--data PATH`), a copy of the config, the checkout's commit and the config notes. A data folder that is a link is followed; a link inside the data that leads outside the folders archived is refused (give where it leads with `--data` too). Every file that was there both before and after `tar` ran has to be in the archive, and only a snapshot whose every check passed gets the file `snapshot-complete`. Then `identity.key`, `verify.key`, `members.json` and `board-token` in `FRONTDOOR_SECRETS_DIR` (default `~/.config/stackshot/frontdoor`). Keys and members that are there already are kept, a `board-token` that is also another file (a link to `oauth.env`, to a key, or to a file the config names) is refused, and the printed removal command names only the files this run made. No value is printed. A signal that asks the run to end ends the program it runs and prints those removal lines; the snapshot it began is not marked complete.
4. Add the front door's tables to the config, check them, and turn on the front door, the sign-in service and a splitter on a test port such as 8025 ([The splitter](#the-splitter)).

### The cut-over

Save and push one config change: `[server] port = 8021`, `[behind_frontdoor]` with the front door's `identity_secret_file` and `members_file` and `board_name = "main"`, the board's `url` in `[[frontdoor.backends]]` and `[frontdoor_signin] board_verify_url` on 8021, `accept_portal_token` set to the answer you want, and `[frontdoor_splitter] listen_port = 8020`. Then run `tools/frontdoor_cutover.py` within five minutes: it looks that far back in the board's journal for the line that a key waits for the next restart.

It needs the config in a git checkout (it pulls with `--ff-only`) and these units installed: the board, the minute runner (`[runner] process = "unit"`), the portal sync (`[portal] account_id`), the front door, the sign-in service and the splitter. An instance without one of them is refused.

Before the restart it stops at the first check that fails and restarts nothing: nothing answers on 8021 yet; the release hold has 15 minutes or more left and no release is queued or running; the snapshot holds a single-user config this code can load, its notes and its archive, is marked `snapshot-complete` and is from the last 24 hours; no drop-in of an earlier way back is in place; the pulled config holds the settings above and has no note the snapshot's list lacks; the front door holds the board's machine token; `./install.sh units`; the journal of the board's current run says `server.port` waits for the next restart; the board still answers on 8020. Then it stops the test splitter, clears a failed state of the board and the minute runner, and asks once more that the hold is on and no release runs. A signal during the pull is answered when the pull has ended. A run that stops here prints what the machine shows and what to do about it: how to undo what was saved and turned on, how to finish an earlier way back that is still in place, or that a switch already made needs no second cut-over; and it says so when it had asked for the test splitter to be stopped.

A window of 300 seconds starts at the board's restart. The checks have its first 210 seconds; the last 90 are kept for the way back (`FRONTDOOR_SWITCH_WINDOW`, `FRONTDOOR_SWITCH_RESERVE`; never more than half of the window is kept). The board and the minute runner restart; 8021, 8030 and 8031 answer; the board refuses a call without the front door; the splitter is enabled and started; the portal sync restarts; `stackshot.frontdoor.check --installed` passes; 8020 and the public address answer and refuse a call without a sign-in. When all pass it exits 3 and prints the manual checks, the time they are due, the undo command (`UNDO`) and, for a switch that is kept, `tools/frontdoor_undo.py --apply --drop-saved` (`KEEP`). Run the undo at once if a check fails or they are not all done by then. When they pass, remove the saved copy with the `KEEP` command and end the hold.

### The way back

A failed check, an error, a signal (`INT`, `TERM`, `HUP`, `QUIT`, `USR1`, `USR2`) or the end of the checks' time after the restart brings the board back with no person needed. Because the pulled config still shows the switch at that moment, the board comes back on the saved copy of the single-user config, which the cut-over put at `~/.config/stackshot/frontdoor-rollback/stackshot.toml` before it restarted anything:

1. the splitter is disabled and stopped;
2. a drop-in, `zz-frontdoor-rollback.conf`, points `STACKSHOT_CONFIG` of the board, the minute runner and the portal sync at the saved copy;
3. the board is restarted and answers on 8020; then the other two are restarted and the public address is checked.

**What the 300 seconds bound.** From the first restart to the board answering on 8020 again, as far as this script's own waiting goes: each program it runs is ended at its limit, with everything it started in its process group, and in the way back each limit is a share of what is left of the window (the restart of the board gets all but one share, which is kept for its answer; while there is also a saved copy to fall back on, a try on the config on disk gets half). Inside that window the portal sync's restart is asked for and not waited for. The way back prints how long after the first restart the board answered. It does not bound what `systemd` does: a job whose `systemctl` call was ended goes on, and a board that takes longer than its share to stop or to start is reported as failed (exit 5). A call after the board's answer still gets a few seconds when the window is over, so the script itself can end a little later. The manual checks and a run of the undo by a person are not bounded by it.

The way back ignores the signals above from its first change to its end, run by the cut-over or by a person. The drop-in holds across a reboot. Every end of this way, a failed one included, prints what is left as `OPERATOR` lines:

1. revert the commits of the switch in the config's repository and push;
2. pull on the board's machine;
3. run `tools/frontdoor_undo.py --apply`, which goes back to the config on disk (below);
4. end the release hold, when step 3 has passed.

Until step 3 the board does not see changes to the config, other units and command-line calls read the pulled config, and releases should stay held (a deploy would look for the board on the pulled config's port). A hold ends by itself after two hours at most, so hold again if the revert takes longer.

The undo also works on its own, and which way it goes is read from the config on disk.

**With the config reverted** it goes in this order:

1. it asks the checkout's code to load the config (`python -m stackshot.core.config check`). When the code cannot, it changes nothing, prints the command that shows why, and prints the same run with `--saved`;
2. it disables the splitter, which runs on for the moment;
3. it removes the drop-ins of an earlier way back (that file only; other drop-ins of those units stay) and runs `./install.sh units`. When either fails, nothing is restarted and the drop-ins are put back;
4. it stops the splitter; if the splitter still runs, nothing is restarted and the drop-ins are put back;
5. it restarts the board and waits for its answer on 8020. A board that does not come up is put on a saved copy of the old config, when there is a usable one (exit 4);
6. it restarts the other two, checks the public address and removes the saved copy (`--end-hold` also ends the release hold).

When this way ends incomplete (exit 5), it prints the run that puts the board on a saved copy (`--saved`, with `--snapshot DIR` where one is needed).

**With the config still switched, or with `--saved`,** the board comes back on a saved copy: `--snapshot DIR` names the snapshot whose config to use. Without it the saved copy is taken, unless no unit reads it and it is more than a day old (it may be from an earlier switch). With no usable config, one the checkout's code cannot load included, it refuses, changes nothing and prints the steps for a person.

The cut-over's own run of the way back has no one to ask: when the config on disk is a single-user one that the code cannot load, whose units cannot be set up or on which the board does not come up, it takes the saved copy.

**No data is restored or removed** by either way: records written since the snapshot stay. The archive is there for a person; putting it back drops what was written after it was made.

A cut-over that is killed with `SIGKILL`, or whose machine goes down, brings nothing back: run the undo then. Once the switch stays, run `tools/frontdoor_undo.py --apply --drop-saved` (refused while a unit reads the copy), and remove the snapshot when it is no longer wanted. A later way back while the config shows the switch then needs `--snapshot DIR`.

## The one tool set

The tool list is one board's tool list, whichever boards the caller is on, with each tool's schema as the board gives it plus one optional property, `board`. A caller on several boards must pass `board` on each call; a caller on one need not. When the caller is a member of the brain, the brain's tools are listed beside them (a brain tool takes no `board`). The list shows only the caller's own backends and lists each live, so a backend that is down is named in a warning to the client and left out, and the list fails only when none answers. With no caller (the server's own start) the list is empty.

A board tool that already has a property named `board` is not offered (the front door routes by that name, so the tool would be ambiguous) and the log says so; the other tools of the board are listed as usual.

A brain tool the brain's credential does not list is not offered: the list is the credential's own, so an admin tool of a read-and-write credential is not there and a call to it is refused.

## The refusals

Each is a tool error whose text a client shows as it is; a refused tool list is a protocol error (invalid request) with the same text:

| When | Text |
| --- | --- |
| on several boards, no `board` | `board required: you are on 2 boards (a, b); pass board='<name>' on this call.` |
| a board that is not the caller's, or does not exist | `board '<x>' is not one of your boards. You are on: a.` |
| a member of no board | `you are not a member of any board.`, followed, where the identity is an address, by `The address that signed in: <address>.` |
| a sign-in a registration refuses ([Inviting a person](#inviting-a-person)) | `you are not a member of any board. <address> signed in and is not let in. <reason>` |
| every backend of the caller is a board that does not list the caller (its members and the front door's differ), on a list or a call | `Refused: <identity> is not allowed on this board` |
| a board down, on a call | `board '<b>' did not answer (unreachable). Other boards you are on are unaffected.` |
| every board of the caller down, on a list | `none of your boards answered (b). Check /healthz.` |
| a brain tool not in the credential's list | `tool '<name>' is not offered to this connection (its credential is limited to what the tool list shows; admin-scoped tools are not part of it).` |

## A backend that does not answer

Every wait for a backend has a limit taken from `backend_timeout_seconds` (default 10, a number above 0 and up to 300): the tool listing and the reading of a backend's instructions give up after that long in total, the connection and handshake of a call after that long, and each health check after the smaller of that and 5 s in total (one deadline for the connection, the request and the first line of the answer, so an answer that arrives a byte at a time is given up on at the deadline, and no thread is held while connecting or reading). The limit is not the whole cost of a request: a request that asks one backend twice (a failed call asks again at once for its health) can cost about twice the limit, and closing a connection that was given up on can add a few seconds. A backend that accepts a connection and never answers is treated like one that refuses it: it is skipped for that request (named in the warning of a list, left out of the instructions text, `did not answer` on a call to it) and asked again at the next one, and the caller's other boards are not held by it. A tool call itself has no total limit, since a tool may run long and report progress.

## The instructions text

The front door writes its own: the `preface` of the config, a line naming the caller's backends, then each backend's own instructions verbatim (backends with the same text share one block). Each backend's text is read live and kept five minutes for the caller it was read for (a board gives its text to its members only, so one caller's text is never handed to another); a backend that does not answer, or gives the caller no text, is left out and asked again at the next request.

## Health

`GET /healthz` is open and answers JSON, one entry per backend (`ok`, the HTTP status or the error, the time in milliseconds): 200 when every backend answers its `health_url`, 503 when one does not. The status is read from the first line of the answer, which may be at most 64 KiB (a longer one reads as down), and a redirect is not followed (its status is the answer). A `health_url` may be `https`: the certificate is verified, so a backend with a self-signed certificate reads as down. Proxies of the environment are ignored (a backend is reached directly), and the request sends only `Host`, `Accept` and `Connection`: no credential and no identity header. An answer is reused for `health_cache_seconds`; a call that fails checks again at once, a list uses the answer it has.

Streaming progress and log notifications of a tool call pass through as they arrive; the identity gate is plain ASGI and holds nothing back.

## Checked by

`tests/frontdoor_run_scenario.py` is the run with real processes: a front door in front of two boards (`main` and `side`), each its own process with its own config, store, port, bearer token, copy of the signing secret and `[behind_frontdoor]` table, and a third board with no table, all on loopback ports chosen at run time under one scratch folder (nothing of an instance is read or written). The test plays the reverse proxy and checks, in a round it runs four times (at the start, then after the front door, `main` and `side` are each stopped by their PID and started again, one after another):

- Each member signs in through the door and each board records the person the proxy named, in its own store and never in the other's; an identity header the client sends itself is not taken for the caller, and the caller's own `Authorization` stops at the door.
- The door's refusals: no identity header (401), a caller on no board, two boards and no `board`, a board that is not the caller's (nothing is written).
- The board with the door left out: a signed identity the board's members do not list is refused by the tool; no signed identity, one signed with another secret, altered, cut short, older than the replay window, dated ahead, or a bare name is each refused 403 with the board's sentence; a signed call with no bearer, or the wrong one, is refused 401 (the door's credential is still the board's sign-in); the health route is open.
- A member removed from the members file is refused at the next call on both boards (on an open session through the door and on an open session at each board) and let back in when she is put back, whether the file is edited in place, replaced by a rename or edited to a new text of the same size (a board's cache of the file never keeps a member); a file that is broken or missing lets nobody in, a valid signature included.
- A restart: the part is down, the other part answers (the door says the board did not answer and its `/healthz` is 503; each board still takes a call signed for it with the door gone); the member is removed from the file before the part starts again and the part refuses her at its first call (a start reads the file afresh); she is put back and is served at the first call, with `/healthz` back to 200 inside a few seconds; what each board recorded before the restart is still there.
- The signing secret rotated in the files of the boards and of the door, one after another with no restart: while they differ the board refuses the door's call, when they agree the call is served and an identity signed with the old secret is refused.
- A board with no `[behind_frontdoor]` table serves an unsigned call, ignores a header that looks like a signed identity and records no person.

The other scenarios cover the pieces, in one process:

`tests/frontdoor_board_scenario.py` covers the board's side: the settings and their notes, the check of one signed identity (every refusal, the window, a rotated secret), the members read from the front door's file (the format, a change on an open session, a file that is missing or wrong), the guard as a wrapper, the real board over HTTP and the front door's own transport against it, a board with no table, which is as it was, and a real board with sign-in on that offers the token check (the route's place among the app's routes, the header's name and the signed word as the service writes them, the portal's machine token, a token the board does not know, a bearer that `/mcp` refuses, a 401's `WWW-Authenticate` against `/mcp`'s own; Google's own check of a grant is called by no test). `tests/members_only_scenario.py` covers who is answered at all: members, the machine token, someone who is no member, a removed member, no token and auth off, over HTTP in both of the client's connect modes, on a board that signs people in itself, on a board behind a front door and through the front door. `tests/frontdoor_scenario.py` (stand-in boards and a stand-in brain on loopback ports) covers the schema diff against a single board, the routing and every refusal text above, concurrent calls of several sessions with no cross-talk, that the caller's bearer never reaches a backend, streaming, a backend that is down, a backend that accepts a connection and never answers (initialize, list, call and `/healthz` return within the bound), a health URL that answers a byte at a time (the list, `/healthz` and 40 lists at once return within the bound and the next member is not held), a member removed from the members file on an open session, the instructions text, the signed identity, the no-caller list and the config notes.

`tests/frontdoor_units_scenario.py` covers the units: what `install.sh` renders with and without the tables, that none is enabled or started, the splitter's refusals to render and to start, and the splitter's Caddyfile (with a real Caddy where one is on the PATH). `tests/frontdoor_realcall_scenario.py` runs the real-call check against real processes, the deploy's use of it and the command that copies the machine token. `tests/release_hold_scenario.py` covers holding releases. `tests/frontdoor_switch_scenario.py` runs the live switch scripts against stand-ins for every program they call (the board's own check of a config also for real, in one case): each refusal, each failed check of the cut-over before and after the restart, signals, the lock of one run at a time, the window and what each program may take inside it, what the snapshot has to hold, the way back on a saved and on a reverted config, a reverted config that the code cannot load or that the board does not come up on, and printed commands in paths with a space.

`tests/frontdoor_verify_scenario.py` covers the token check for the sign-in service: the `verify_secret_file` settings and notes, every refusal of the signed header, a rotated secret, a verify secret that is the identity secret, and the route over a stand-in sign-in provider (a good token, the portal's, no bearer, an unknown token, a token with no address, a check that raises, a board with no sign-in, that the route itself never asks about the token of a refused request, and that the bearer is read as the MCP library's middleware reads it).

`tests/invites_access_scenario.py` checks [who reads and writes](#who-reads-and-writes) over real HTTP in both of the client's connect modes, on a board that signs people in itself and through the sign-in service and the front door: a stranger, a person before and after being added, a refused sign-in, a removed person and a removed member, each against the instructions text, the lists, the reads, every tool and what the store holds afterwards. `tests/invites_scenario.py` covers inviting a person, with the real board (Google's token check stood in for), sign-in service and front door in one process: the settings and their notes, the registration and removal in the members file, the verified address and the recorded account, every refusal at the tools, the browser sign-in, the token check and the front door, who may invite, the setup page and its limits, the redirect URIs against the library's own matcher, and a board with no `[invites]`. No real Google sign-in and no real app is part of it.

`tests/frontdoor_signin_scenario.py` covers the sign-in service over a stand-in board: the settings and their notes, the refusal to start on a shared secret, the start where only the `server` extra is installed (and the refusal when a module cannot be loaded), the identity for each form of member, the address written as a member's key, the machine token off and on, the 401 and its passed-on text, every case that is 503, more checks at once than there are connections over a board that stalls, the cache (reuse, expiry, bound, off, and that a refusal or a failure is never kept), what is sent to the board (no cookie, no proxy, no redirect followed), and that nothing of the request is echoed or logged. `tests/frontdoor_signin_run_scenario.py` runs it with real processes (two boards, a front door and a service for each board, each service with the `server` extra only): a caller's token is recorded on the boards under the member's key, the machine token is refused unless switched on, a query string is in no log, and a board that is down, a restart of the service and a rotated secret answer as above. Where `caddy` is on the PATH it puts a real Caddy in front with the block above as it is written here, and checks which paths reach a board without a token, however a path is written; elsewhere it says that it skipped those checks.
