# Holds on a session's inbox

What this page covers: how a tool on another machine holds and releases a session's inbox, asks the server whether a line waits for a session, and sends a line to a server that is not on its own box. Back to the [README](../README.md).

A fleet tool that relaunches a pane holds that pane's inbox first, so a line the puller hands out in that moment is not taken by a process that is going away, and a tool that puts a pane to sleep asks whether a line waits for it. On the server's own box both are files. On another box they are calls to the server, and the server keeps reading the files too, so nothing has to change on every box at once.

## The files the server reads

For each source (`hub` and `msg`) the state's `anchor-hub` folder holds three hold files, one key per line: `held-<source>.txt` (the keys another tool holds), `held-resume-<source>.txt` (a reboot's resume) and `held-api-<source>.txt` (the keys held through the calls below, written by those calls and nothing else). `stackshot/fleet/inbox.py` (`take`, `blocked`) and `stackshot/fleet/push.py` skip a line whose address, transcript id, name or permanent id is a key in any of the three. The inbox itself is `<state>/inbox/<source>/<id>.json`, one JSON object a line with `to`, `uuid`, `name` and `pid`.

## The calls

All four are client API calls, `Authorization: Bearer <machine token>`, and each has a `client.py` form (`stackshot/fleet/client.py`). The keys are the session's transcript id and its name, as the file hold lists them.

| Call | `client.py` | Body or query | Answer |
|---|---|---|---|
| `POST /client/inbox-hold` | `post inbox-hold <key> [<key> ...] [--kind msg\|hub] [--minutes N]` | `{"keys": [..], "kinds"?: ["msg", "hub"], "minutes"?: N}` | `200 {"held": {"msg": [..], "hub": [..]}, "expires": <epoch or null>}` |
| `POST /client/inbox-release` | `post inbox-release <key> [<key> ...] [--kind msg\|hub]` | `{"keys": [..], "kinds"?: [..]}` | `200 {"released": {"msg": [the keys that were held], "hub": [..]}, "held_elsewhere"?: [..]}` |
| `GET /client/inbox-holds` | `get inbox-holds [<key>]` | `?key=<key>` (optional) | `200 {"holds": [{"kind", "key", "origin", "since", "expires"}], "now": <epoch>}` |
| `GET /client/inbox-waiting` | `get inbox-waiting <name>[,<transcript id>]` | `?key=<name>[,<transcript id>]` (1 to 20 keys) | `200 {"keys": [..], "hub": n, "msg": n, "waiting": bool, "held": {"hub": bool, "msg": bool}}` |

- **Hold.** The keys go into `held-api-<source>.txt` of each named kind (without `kinds`, both, as the file hold does): the call writes its own file, under its own lock, and never reads and rewrites a file another tool writes. Holding a key that is held is a refresh (it is the touch of a hold still wanted), and a key that another tool holds too is held here as well, so it stays held when that tool lifts its own hold. `keys` is 1 to 20 keys, each one line of at most 200 printable characters (surrounding whitespace is dropped, as the server's readers drop it; a control or line-separator character is refused); `kinds` is `hub`, `msg` or both; `minutes` is more than `0` and at most `1440` (`0` is refused: a hold made by the call always has an end), and left out it is `[client] inbox_hold_minutes` (default 10). One source's API file holds at most 500 keys: a hold that would pass it is a `400` naming the cap, and holding a key that is already there is no new key. A bad body is a `400` with the reason. `expires` is the end of the holds made (`null` only when the operator set `[client] inbox_hold_minutes` to `0` and the call left `minutes` out).
- **Expiry.** Each hold made by the call carries its time in `<state>/anchor-hub/holds-api.json`; the server's minute tick takes the key out of `held-api-<source>.txt` when the time is up (a journal line says so), so a relaunch that died and never released leaves nothing held for good, and drops the time of a key that is no longer in that file. The sweep runs on the minute tick, so a hold ends up to a minute after its time. The call saves the time before it writes the key, and a key found in `held-api-<source>.txt` with no time (a times file that was lost or unreadable: it is kept as `holds-api.json.bad` and the keys get a new time) is given one of `inbox_hold_minutes` from then, so it ends too. The sweep touches only the call's own file: a key in `held-<source>.txt` or `held-resume-<source>.txt` is never expired or removed by it.
- **Release.** Takes the keys out of `held-api-<source>.txt` of the named kinds and forgets their times. It never touches `held-<source>.txt` or `held-resume-<source>.txt`: a key that is still held in either one after the release is named in the answer's `held_elsewhere` (a list of keys, present only when there is one), and the tool that wrote it lifts it. Releasing a key that is not held is a `200` with an empty list for that kind.
- **List.** One row for each kind, key and file that holds it. `origin` says which: `api` (`held-api-<source>.txt`, made by the hold call, with `since` and `expires` as epochs, `expires` null for a hold with no time), `file` (`held-<source>.txt`, another tool's) or `resume` (`held-resume-<source>.txt`). A key held in two files has two rows. A fleet tool that frees keys no ledger row of its own accounts for reads this list in place of the files.
- **Waiting.** Counts the lines in `<state>/inbox/hub` and `<state>/inbox/msg` whose `to`, `uuid`, `name` or `pid` equals one of the keys, held or not (a held line is still waiting): the same test a tool makes today by looking into those folders, answered by the server. `held` says whether a key is held in each source.

Refusals are `400` (a bad key, kind or minutes, or the 500-key cap) or `401` (no machine token). A call that cannot reach the server is no answer: the tool decides what that means for its relaunch or its sleep, and must not take it as "nothing waits" or "held".

## Sending a line from a box that is not the server's

`stackshot/fleet/push.py` is the delivery script scripts call. By default it runs on the server's own box and writes the line into the local inbox and queue folders. On a box that is not the server's those folders are nobody's, so a line "queued" there is never read. Two settings in `[client]` decide:

- `push_mode = "local"` (the default, today's behaviour): the local folders.
- `push_mode = "server"`: the line is sent to the server through the client API's `message` call (`client.py message`, this box's token, the sender `--from`, `$PUSH_FROM` or the calling program's name), and the server delivers it by its own rules. A line sent this way is a message: a message to a front agent is delivered only when it is for the person, the source is always the message's, and a pane on this box is reached through its puller like any other.
- `push_mode = "auto"`: `server` when the client URL (`$STACKSHOT_URL`, `<secrets>/client.url`, else `[client] url`) names another machine, `local` when its host is loopback or this box's own name. This is the one setting a config file shared by the server's box and the others can carry. A different machine whose bare host name (the part before the first dot) is the same as this box's counts as this box under `auto`; `server` is the way to be explicit.

`$ANCHOR_PUSH_MODE` (`local`, `server` or `auto`) overrides the setting for one process, and the server's own programs (`server`, `minute`, `anchor-hub`, `audit`, `audit-run`, `router-live`) set it to `local` for what they start, so a server box can never send a line to itself. In server mode push.py exits 0 when the server delivered the line or holds it for the session's next turn, 1 when it waits in the server's inbox, 2 when the server refused it, there is no sender, or it was not passed on, and 4 when the server could not be reached, this box has no token yet, or the server's delivery failed (nothing was queued on this box: a caller that must not lose the line tries again). `--flush` has no queue to flush there and exits 0.

## Settings added

| Key | Default | Where |
|---|---|---|
| `client.inbox_hold_minutes` | `10` | the server's config |
| `client.push_mode` | `"local"` | the config of a box that runs push.py (`$ANCHOR_PUSH_MODE` per process) |

Both are in `stackshot.example.toml` and [Configuration: project agents, runners, anchor-hub, router, auth and client](configuration-integrations.md).

## Files of another tool

The API owns `held-api-<source>.txt` and its times file, and writes nothing else. On the server's own box a session manager (the fleet tool that relaunches panes) may still write `held-<source>.txt` itself, under a lock of its own, and a reboot's resume writes `held-resume-<source>.txt`. The server honors all three files, and the calls never read and rewrite a file another tool writes, so the writers cannot erase each other's holds. A hold in another tool's file is lifted by that tool: `inbox-release` names such a key in `held_elsewhere` and leaves it, and `inbox-holds` lists it with `origin` `file` or `resume`. The session manager may free, on its own clock, keys in its own file; that does not touch the API's holds, which end by the API's own time or by a release.

## Who may hold what

The calls take the same machine token as every other client call, and the server checks the token, not whose session a key names: any machine's token can hold or release any key, and a key need not name an existing session. That is the reach of the `message` call (any session can be written to) and of `ack` (any line id can be confirmed), the two other calls that name a session or a line by key; `poll` and `drain` are scoped to the calling machine's own sessions. A hold is bounded: a call asks for more than 0 and at most 1440 minutes (`minutes: 0` is refused; the one exception is an operator who sets `[client] inbox_hold_minutes` to `0` and a call that leaves `minutes` out), a source's API file holds at most 500 keys, and an unreadable times file leaves no key without an end. A held line is not lost: it waits until the hold ends or is released. The request log records each call's route and the machine that made it.
