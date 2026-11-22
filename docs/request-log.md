# The request log

What this page covers: the server's request log (what a line holds, where the files are, how long they are kept and what is never written) and the one command that summarizes it. Back to the [README](../README.md).

The server writes one JSON line for every HTTP request it answers, plus a line when it starts and when it stops cleanly. It is there to read the server's health and latency back: how long a page or a tool call takes, which routes fail, when the server restarted. It is on by default and needs no setting.

## The files

- The directory is `<state>/requests/`, where `<state>` is `[paths] state`.
- One file per UTC day, `requests-YYYY-MM-DD.jsonl`. A line is appended as the request ends, under one lock, and flushed at once.
- At the first write of a new day, and at the start, a background thread gzips every finished day's file to `requests-YYYY-MM-DD.jsonl.gz` and deletes the files more than 90 days old. A request never waits for it.
- A write that fails (a full disk, a read-only directory) never fails a request: the server prints one line on stderr, at most once in ten minutes, and the next write tries again.
- A warm [read-only standby copy](read-only-standby.md) writes nothing under its state directory, so it keeps no log.

## What a line holds

| Field | Meaning |
|---|---|
| `ts` | When the request ended: UTC, with milliseconds. |
| `method` | The HTTP method when it is one of GET, HEAD, POST, PUT, PATCH, DELETE or OPTIONS; any other text a client sends as a method is `OTHER`. |
| `route` | The route, never the address: a path parameter's value is replaced by its name (`/items/{key}/answer`); a catch-all is `/{name}`, whatever its first folder; a path no route took is `(unmatched)`. The MCP endpoint is one path, so its route is the JSON-RPC method (`mcp:tools/list`) or, for a tool call, `tool:<name>` of a tool the server has (`tool:{other}` for any other name). The client API keeps its verb (`/client/poll`) only when its handler took the verb; a guess, or a call that was refused before its verb was read (no token), is `/client/{other}`. |
| `status` | The response status (0 when the client left before there was one). |
| `ms` | The request's whole time in milliseconds, from the first byte in to the last byte out. |
| `bytes` | The response size in bytes. |
| `caller` | The machine a client token belongs to (a name the server holds), or the `sender` of an accepted call to a tool the server has, when it is a lower-case label of letters, digits and hyphens (up to 61 characters), the shape of a session's own name; otherwise `anon`. A call the tool layer refused, a made-up tool name and any other `sender` text are `anon`. |
| `err` | For an exception: its type and where it was raised, `<type> at <module>:<function>:<line>`, and nothing it says. For a 5xx the app answered with no exception: `status <n>`. |

A start line is `{"kind":"start","pid":...,"head":"<short commit>","mode":"inline"}` (`mode` is where the minute runner runs, `[runner] process`); a clean stop is `{"kind":"stop","pid":...}`.

## What is never written

The query string, a header, a cookie, an Authorization value, a token, a request or response body, an IP address and a user agent. The route is built from the path alone; a sign-in link's one-time values travel in the query string and never reach the file. No text a client typed freely is written, apart from the one label above: the route is a template or a fixed word, the method one of seven or `OTHER`, the caller a validated label or `anon`. An exception's message is never written, because it can hold anything (a URL with a password, a header, a body); `err` is the type and the place only, and the full message stays in the server's own log with its traceback.

The wrapper that writes the log sits outside every other layer of the HTTP app and passes each message through as it comes: it reads no body, buffers nothing and changes nothing, so a streamed response reaches the client as before.

## The summary

```
python3 -m stackshot requests summary [--since 24h] [--until now] [--top 10] [--route TEXT] [--json]
```

- `--since` and `--until` take a date (`2026-11-22`), a date and time (`2026-11-22T14:30`), or a time back from now (`90m`, `24h`, `7d`). A date or time with no offset is in the instance's timezone, `[instance] timezone`, which is also the zone every printed time is in. A bare date in `--until` means the end of that day. The default range is the last 24 hours.
- The output is a table per route (count, p50, p95 and max in ms, and the 5xx count), the slowest calls (`--top`), the errors (a 5xx or a line with `err`: the count and the first few), the server starts and stops in the range, and the totals (requests and the error rate). A percentile is the value at position ceil(q x n) of the n times in order (p95 of 20 times is the 19th).
- `--route TEXT` keeps the requests whose route contains the text. `--json` prints the same as JSON.
- It reads plain and gzipped files, skips a half-written last line and a missing day, and an empty range prints `no requests in range` and exits 0.
