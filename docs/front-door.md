# The front door

What this page covers: the front door, one MCP endpoint over several boards and a brain for people who sign in through a reverse proxy: how it is run, the sign-in service the proxy asks, its units, the splitter, releases, who the caller is, the one tool set and its `board` argument, every refusal text, the credential each backend is called with, the instructions text, the health route and what is checked. Back to the [README](../README.md).

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
| no bearer, an empty one, not `Bearer`, a token the board does not know, expired or revoked, or one with no address | 401 `{"error": "invalid_token"}`, with the `WWW-Authenticate` header below |
| the check itself raised | 503 `{"error": "unavailable"}`, never 401 |
| the board has no sign-in (`[auth] mode` off) | 404 |

The check is the board's own `verify_token`, the call its browser sign-in makes: the token's signature, the stored mapping, and Google's own check of the grant at every call, so a grant revoked at Google is refused at once. What the library swallows (a network failure reads as "no such token") arrives as 401, as it does for a direct call to the board. Every answer is `Cache-Control: no-store`, and no answer holds the token.

A 401 carries the `WWW-Authenticate` value the board's own `/mcp` sends for the same request: with no `Authorization` header the challenge names no error, with one it says `error="invalid_token"`, and both name the `resource_metadata` address a connector discovers the sign-in by (and the scopes to ask for). The board takes the value from the library's own guard on `/mcp`, so it follows the board's `[auth] base_url` and MCP path. A sign-in service that passes it on gives a connector the same sign-in discovery as the board. No other answer (403, 404, 503, 200) carries the header.

**What the sign-in service can rely on.** A 200 says the token is valid, not that the account is a member of any board: the sign-in service checks membership. The service treats any 5xx as a refusal. The signed header is bound to neither the token nor the request, so whoever gets hold of one can send it again, with any token, until it is older than `identity_max_age_seconds`: keep that hop as private as the one the signed identity takes. The verify secret and the identity secret must differ, because the service holds the verify secret and with the identity secret it could sign a call as any member: a board that checks identities and whose two files hold the same value answers no check, and its log says why.

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
	# The board's own sign-in, which a connector uses before it has a token. The match is on the request line as it arrived:
	# a `path` matcher would ignore case and tidy the path before comparing, and the board does neither.
	@signin vars_regexp {http.request.orig_uri} ^/(\.well-known(/[A-Za-z0-9_-][A-Za-z0-9._-]*)+|authorize|token|register|consent|auth/callback)(\?.*)?$
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
- Six kinds of path go to the board unchecked, and no others: `/.well-known/...` (the discovery documents), `/authorize`, `/token`, `/register`, `/consent` and `/auth/callback`. Everything else goes through the check to the front door, `/mcp` included, and so does one of these paths written another way (another case, an encoded character, a dot segment, a doubled or trailing slash): it needs a token like any other.
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
| anything else: the board's 403 (the two secrets differ), 404 (a board with no sign-in), 5xx, a redirect, an answer that names no ASCII address or no kind of token, no whole answer in `timeout_seconds`, a board that cannot be reached; a secret or members file that cannot be read; a member the file lists under two keys that differ only in surrounding spaces, with different boards (a board reads the first entry, the front door the last); an identity that is not printable ASCII; a fault of the service | 503 with a sentence and no identity header. Never 200, and never 401: a 401 tells a connector that its token is no good |

A board's 200 says who the token is for, never that the person is a member: the service decides that from the members file. A person no member holds is not refused here (but for the 403 case above): the front door answers `you are not a member of any board.` A member's key goes into a header as it is, so a member who signs in through this service has a key of printable ASCII characters.

**The board's machine token.** The token a board takes as `[auth] portal_identity` (what a portal in front of the board, or a script, holds) passes the board's token check too, which says `"via": "portal"`. The service refuses it unless `[frontdoor_signin]` has `accept_portal_token = true`: that token belongs to one board, and as its person's identity at the front door it reaches every board that person is a member of. Switch it on only where whoever holds the token may use all of those boards: add the line and restart the service. `--check` says whether it is accepted.

A 200 of the board that the service accepts is reused for `cache_seconds` (5 by default, 0 turns it off), under a SHA-256 of the token, at most 1024 of them. Nothing else is kept, so a token the board refused is asked about again at the next request, and a token revoked at the board keeps working through the service for at most that long. The secret and the members file are read at each request, cached or not.

The service reaches the board directly, whatever proxy the environment names, follows no redirect and keeps no cookie. It holds at most 64 connections to the board; a further check waits for one within its own `timeout_seconds`.

Every answer is `Cache-Control: no-store`. A header the client sends is not repeated in the answer, whatever its name. The log names a request by the first 8 hex digits of a hash of the token and of the identity; no token, secret or address is written to it. It keeps no access log and speaks no websocket protocol (a websocket upgrade is answered as the plain request it also is): Caddy's check carries the query string of the caller's own request, which the service neither reads nor writes. `GET /healthz` answers 200 `{"status": "ok"}` when the secret and the members file can be read and 503 `{"status": "degraded"}` when not; it does not ask the board.

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

## The one tool set

The tool list is one board's tool list, whichever boards the caller is on, with each tool's schema as the board gives it plus one optional property, `board`. A caller on several boards must pass `board` on each call; a caller on one need not. When the caller is a member of the brain, the brain's tools are listed beside them (a brain tool takes no `board`). The list shows only the caller's own backends and lists each live, so a backend that is down is named in a warning to the client and left out, and the list fails only when none answers. With no caller (the server's own start) the list is empty.

A board tool that already has a property named `board` is not offered (the front door routes by that name, so the tool would be ambiguous) and the log says so; the other tools of the board are listed as usual.

A brain tool the brain's credential does not list is not offered: the list is the credential's own, so an admin tool of a read-and-write credential is not there and a call to it is refused.

## The refusals

Each is a tool error whose text a client shows as it is:

| When | Text |
| --- | --- |
| on several boards, no `board` | `board required: you are on 2 boards (a, b); pass board='<name>' on this call.` |
| a board that is not the caller's, or does not exist | `board '<x>' is not one of your boards. You are on: a.` |
| a member of no board | `you are not a member of any board.` |
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

`tests/frontdoor_units_scenario.py` covers the units: what `install.sh` renders with and without the tables, that none is enabled or started, the splitter's refusals to render and to start, and the splitter's Caddyfile (with a real Caddy where one is on the PATH). `tests/frontdoor_realcall_scenario.py` runs the real-call check against real processes, the deploy's use of it and the command that copies the machine token. `tests/release_hold_scenario.py` covers holding releases.

`tests/frontdoor_verify_scenario.py` covers the token check for the sign-in service: the `verify_secret_file` settings and notes, every refusal of the signed header, a rotated secret, a verify secret that is the identity secret, and the route over a stand-in sign-in provider (a good token, the portal's, no bearer, an unknown token, a token with no address, a check that raises, a board with no sign-in, that the route itself never asks about the token of a refused request, and that the bearer is read as the MCP library's middleware reads it).

`tests/frontdoor_signin_scenario.py` covers the sign-in service over a stand-in board: the settings and their notes, the refusal to start on a shared secret, the start where only the `server` extra is installed (and the refusal when a module cannot be loaded), the identity for each form of member, the address written as a member's key, the machine token off and on, the 401 and its passed-on text, every case that is 503, more checks at once than there are connections over a board that stalls, the cache (reuse, expiry, bound, off, and that a refusal or a failure is never kept), what is sent to the board (no cookie, no proxy, no redirect followed), and that nothing of the request is echoed or logged. `tests/frontdoor_signin_run_scenario.py` runs it with real processes (two boards, a front door and a service for each board, each service with the `server` extra only): a caller's token is recorded on the boards under the member's key, the machine token is refused unless switched on, a query string is in no log, and a board that is down, a restart of the service and a rotated secret answer as above. Where `caddy` is on the PATH it puts a real Caddy in front with the block above as it is written here, and checks which paths reach a board without a token, however a path is written; elsewhere it says that it skipped those checks.
