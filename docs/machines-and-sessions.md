# Session links and the Machines panel

What this page covers: how the board links to a session, and what the Machines panel shows for each machine and package. Back to the [README](../README.md).

**Session links.** Both come from the fleet tool (see [The fleet tool](fleet-tool.md#the-fleet-tool)), and both are off until configured.
On the web pages (the board, the item pages, the project pages and inline mentions) a session's name links to its view in
the fleet tool's web UI, `client.session_view` with the name url-quoted for `{name}` (on an instance run with sala, sala's
`https://sala.example.com/#s={name}`), in a new tab, while the session holding that name has a live pane by the one
presence rule (`fleet.present`: running, or relaunching within the grace); a name with no live pane, a cloud or Cowork
session's included, is plain text (link the board and sala both ways). board.md, the brief
and the `sessions` tool give the `url` the fleet tool writes for that transcript id in its own live store
(`client.session_links`, `<dir>/<letter>/sessions.json`): on such an instance a web-terminal link for a pane on the server
box. A session the store has no row for, or a row with an empty url, is named there without a link, whatever its Remote
Control bridge does; a missing or unreadable store is logged once and leaves every pane without a link. A cloud or Cowork
session (`cse_…`) keeps its claude.ai link from `stackshot/core/cloud.py` there. This is the one read of the fleet tool's files the server
makes since an earlier change; names, machines and presence still come from the
server's own clients.

**The Machines panel.** The board shows one card per machine, its name as the card's bold first label, with a row per
package in `[machines_panel]`: the installed version and `latest ✓`, `→ <latest version>` (in the text colour, on the row's own line), `offline` (from the puller's check-ins) or
`latest unknown`, against the latest from npm or GitHub releases (`stackshot/fleet/versions.py`). A failed setup step or update is a card of its
own under the machine's. The cards are the fleet's machines (sala's letters) and then the `[machines_panel] ssh_hosts`, machines with
no puller (spare-box): **one card per machine**, keyed by the full hostname: a host that is also a fleet machine (spare-box, while the config still lists it in `ssh_hosts`) is the fleet machine's card, with the ssh-probed version where the host has the package and answers, and the fleet's row for any package only the fleet knows, or for every package while the probe fails (`fleet.machines_order` gives the one list of names: the publisher, then the fleet by letter, then the remaining hosts in config order). An `ssh_hosts` name merges only when it equals the fleet name exactly (the full hostname). The publisher runs one `ssh -o BatchMode=yes` call per host on each forced refresh (the timer publish,
every `[publish] every_minutes`, and `bump`), 10 s at most, with each package's version command (`ssh_cmd`, else the `cmd:` command, else
`self_cmd`); a package the host lacks gets no row, an unreachable host shows `offline` with the versions it last had. A machine card, fleet or ssh host,
carries no hover text at all. The read is cached in `<state>/site/versions.ssh.json`.
