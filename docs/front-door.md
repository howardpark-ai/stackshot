# The front door

What this page covers: the front door, one MCP endpoint over several boards and a brain for people who sign in through a reverse proxy: how it is run, who the caller is, the one tool set and its `board` argument, every refusal text, the credential each backend is called with, the instructions text, the health route and what is checked. Back to the [README](../README.md).

The front door is a separate program (`python -m stackshot.frontdoor`, package `stackshot/frontdoor/`). The board server does not import it and does not read its settings. This page is stage 1, the module: nothing in it is installed or started by `setup`; a person who runs it writes the proxy and the unit themselves.

## Run it

```
uv run --project <checkout> --locked --extra server python -m stackshot.frontdoor            # serve
uv run --project <checkout> --locked --extra server python -m stackshot.frontdoor --check    # read the settings, print what would run, exit
```

It needs the `server` extra (FastMCP is already in it, so there is no new dependency). The settings are the `[frontdoor]` table and one `[[frontdoor.backends]]` table per backend of the config file ([Configuration: integrations](configuration-integrations.md), `frontdoor.*`). It does not start (exit 2, the reason on standard error, never a secret) without an `identity_header`, a `members_file` and one usable backend. A backend entry that is wrong is left out, named in the config notes (`stackshot doctor` prints them), and the others are served.

## Who is calling

A reverse proxy in front of it checks the sign-in (for example Caddy's `forward_auth`) and sets one header, named by `identity_header`, to the caller's identity. The front door trusts that header and nothing else: a request to `/mcp` without it is refused with HTTP 401, and `/healthz` is open. The header is plain text: the front door cannot tell a header the proxy set from one a client sent, so the setup has two requirements. First, only the proxy may reach the front door: it listens on the loopback address by default (`listen_host`; any other address is named in the config notes, not refused, and keeping everything but the proxy away is then the setup's job). Second, the proxy must drop or overwrite any copy of that header the client sends itself (with `forward_auth` that is the step that copies the header from the sign-in answer). The signature described below covers only the hop from the front door to a backend; nothing signs the hop from the proxy to the front door. The caller's own `Authorization`, `X-Api-Key` and `Cookie` headers stop at the front door: each backend is called through a transport that sets that backend's headers itself (`forward_incoming_headers=False`).

`members_file` is a JSON object `{"alice": ["main", "side"], "bob": ["main", "brain"]}`: a member and the names of the backends the member is on. It is read at each request. A file that cannot be read makes nobody a member, never everybody.

## What a backend is called with

The front door's own credential, never the caller's: `Authorization: Bearer <the token in token_file>`, or an OAuth access token the front door asks for with the client credentials in `client_id_file` and `client_secret_file` and the `scopes` listed. A secret file is read as a brain's `secret_file` is: a regular file private to its owner, at most 64 KiB, a printable value of 16 characters or more; nothing it holds is printed or logged.

The caller's identity goes to the backend as a second header, `x-stackshot-identity`, signed: `v1.<identity>.<time>.<HMAC-SHA256>` under the secret in `identity_secret_file` (`stackshot/frontdoor/identity.py`, `sign` and `verify`: a value that is altered, signed with another secret, older than five minutes or dated ahead of the clock does not verify). Stage 1 sends it; the boards do not read it yet.

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
| a board down, on a call | `board '<b>' did not answer (unreachable). Other boards you are on are unaffected.` |
| every board of the caller down, on a list | `none of your boards answered (b). Check /healthz.` |
| a brain tool not in the credential's list | `tool '<name>' is not offered to this connection (its credential is limited to what the tool list shows; admin-scoped tools are not part of it).` |

## A backend that does not answer

Every wait for a backend has a limit taken from `backend_timeout_seconds` (default 10, a number above 0 and up to 300): the tool listing and the reading of a backend's instructions give up after that long in total, the handshake of a call after that long once the connection is open, and each health check after the smaller of that and 5 s in total (one deadline for the connection, the request and the first line of the answer, so an answer that arrives a byte at a time is given up on at the deadline and holds no worker). The limit is not the whole cost of a request: the connection of a call is left to the system's own time for opening one before its handshake starts, and closing a connection that was given up on can add a few seconds, so allow about twice the limit as the worst case. A backend that accepts a connection and never answers is treated like one that refuses it: it is skipped for that request (named in the warning of a list, left out of the instructions text, `did not answer` on a call to it) and asked again at the next one, and the caller's other boards are not held by it. A tool call itself has no total limit, since a tool may run long and report progress.

## The instructions text

The front door writes its own: the `preface` of the config, a line naming the caller's backends, then each backend's own instructions verbatim (backends with the same text share one block). Each backend's text is read live and kept five minutes; a backend that does not answer is skipped and tried at the next request.

## Health

`GET /healthz` is open and answers JSON, one entry per backend (`ok`, the HTTP status or the error, the time in milliseconds): 200 when every backend answers its `health_url`, 503 when one does not. The status is read from the first line of the answer and a redirect is not followed (its status is the answer). An answer is reused for `health_cache_seconds`; a call that fails checks again at once, a list uses the answer it has.

Streaming progress and log notifications of a tool call pass through as they arrive; the identity gate is plain ASGI and holds nothing back.

## Checked by

`tests/frontdoor_scenario.py` (stand-in boards and a stand-in brain on loopback ports) covers the schema diff against a single board, the routing and every refusal text above, concurrent calls of several sessions with no cross-talk, that the caller's bearer never reaches a backend, streaming, a backend that is down, a backend that accepts a connection and never answers (initialize, list, call and `/healthz` return within the bound), a health URL that answers a byte at a time (the list, `/healthz` and 40 lists at once return within the bound and the next member is not held), a member removed from the members file on an open session, the instructions text, the signed identity, the no-caller list and the config notes.
