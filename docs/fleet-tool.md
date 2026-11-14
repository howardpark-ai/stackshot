# The fleet tool

What this page covers: the points of contact between stackshot and an optional fleet tool: session links, lanes, recycles, spawns, reboots, CLI updates and naming. Back to the [README](../README.md).

stackshot runs with no fleet tool installed. A fleet tool is what spawns, relaunches and updates the Claude Code panes and
keeps a web view of them; for example sala (howardpark-ai/salamander), a separate tool installed and
documented on its own. The two meet only through [the stackshot–sala contracts](https://github.com/howardpark-ai/salamander/blob/main/docs/stackshot-contracts.md), one versioned
document kept on sala's side, and through the config keys that name the other side's paths and commands, all of them
empty by default. With every key unset, what they feed is off and nothing fails: session names are plain text, the `lane`
done check is refused, a change no item covers is left for the next recycle, the injected-text marker is not looked for,
and stackshot runs no fleet command. The points of contact:

- **Session links**: the tool's store of links (`client.session_links`; contract [1, Heartbeat fleet store](https://github.com/howardpark-ai/salamander/blob/main/docs/stackshot-contracts.md#1-heartbeat-fleet-store)) and its web view
  (`client.session_view`; no section of its own, the link form is in the same one). Its permanent session ids, `session-registry.json`
  in the same directory, are contract [19, Session registry file](https://github.com/howardpark-ai/salamander/blob/main/docs/stackshot-contracts.md#19-session-registry-file).
- **Lanes**: the tool's lane record (`client.lanes_file`), read by the `lane` done check, and its readings of which lanes
  cannot run (`client.limit_file`, `lane-signin.state` beside the lane record; no longer read by stackshot). A lane word and its old
  alias are one lane in every comparison (the `lane` check; one fixed alias map,
  `lanes.FIXED_ALIASES`, read by `stackshot/core/lanes.py`), in either direction, and the current code is shown; no stored data is renamed. stackshot never writes a lane's plan name or display name in its own text, it reads them from the tool's lane-names file
  (`~/.local/state/salamander/lane-names.json`, or the file `STACKSHOT_LANE_NAMES` names; `{"lanes": [{"code", "display", "aliases"}, ...]}`, every lane
  listed), read again when its modification time changes, never by running the tool. A lane word is taken by its code or any alias (a `lane` check is stored by the code); a refusal
  that lists the tool's lanes shows each code with its display name. With the file missing or unreadable, a lane shows as its code and one line goes to
  standard error. Contract
  [12, Lanes and limit state read by stackshot](https://github.com/howardpark-ai/salamander/blob/main/docs/stackshot-contracts.md#12-lanes-and-limit-state-read-by-stackshot).
- **The injected-text marker** (`said.injected_marker`): what the tool puts first in text it types into a pane. Contract [2, Message marker](https://github.com/howardpark-ai/salamander/blob/main/docs/stackshot-contracts.md#2-message-marker).
- **Recycles**: the command that asks for one once the box is idle (`fleet.recycle_when_idle`, contract [13, stackshot's release asks for a recycle](https://github.com/howardpark-ai/salamander/blob/main/docs/stackshot-contracts.md#13-stackshots-release-asks-for-a-recycle)); the end-of-recycle hook,
  `stackshot/fleet/client.py recycled` (its flags, or the environment under `client.recycle_env_prefix`; contract [4, Post-recycle hook](https://github.com/howardpark-ai/salamander/blob/main/docs/stackshot-contracts.md#4-post-recycle-hook)); the watchdog's reads,
  `stackshot/fleet/client.py recycle-wanted` (prints `<count> <id>[@<epoch>][~<repo>:pr<N>]…`: the second the recycle was asked for, and the item's latest anchored pull request, which the tool waits to see live; [5, Recycle-wanted](https://github.com/howardpark-ai/salamander/blob/main/docs/stackshot-contracts.md#5-recycle-wanted)), `stackshot/fleet/client.py puller-lag` and the `<state>/clients/puller-lag` file the server rewrites on a change
  ([6, Puller-lag file and path unit](https://github.com/howardpark-ai/salamander/blob/main/docs/stackshot-contracts.md#6-puller-lag-file-and-path-unit)).
- **Spawns and renames**: `stackshot/projects/pages.py agent-listed <name>`, which the tool asks before it names a session. Contract [7, Agents-map checks](https://github.com/howardpark-ai/salamander/blob/main/docs/stackshot-contracts.md#7-agents-map-checks). The New session
  form's calls to `/client/projects` and `/client/project*`: [21, the web terminal's project calls](https://github.com/howardpark-ai/salamander/blob/main/docs/stackshot-contracts.md).
- **Reboots**: `reboot-hooks/stackshot-hook` and `reboot-hooks/anchor-hub-hook`, the participants in the tool's reboot. Contract
  [14, Reboot hooks](https://github.com/howardpark-ai/salamander/blob/main/docs/stackshot-contracts.md#14-reboot-hooks), which points to [reboot-contract.md](https://github.com/howardpark-ai/salamander/blob/main/docs/reboot-contract.md) (version 1, in force).
- **CLI updates**: after the tool updates the CLI it runs its post-update command (sala's `SALA_POST_UPDATE_CMD`; on the host `python3 <checkout>/stackshot/web/publish.py bump`). The `bump_versions` tool is a separate way to do the same refresh by hand. Contract [23, CLI update hook](https://github.com/howardpark-ai/salamander/blob/main/docs/stackshot-contracts.md#23-cli-update-hook), described as `stackshot/web/publish.py bump`.
- **Naming**: `fleet.tool_name` (prose only) and `fleet.operator_session` (the session the `sessions` tool names for fleet work). No contract.

Every section linked here is in force. The one proposal in that repository, `session-registry-contract-proposal.md`, is adopted only in
part: its two halves that matter here are interfaces 19 and 20 of the same document. Read those, not the proposal.
