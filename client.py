#!/usr/bin/env python3
"""client.py — one machine's half of stackshot (the design doc). Stdlib only, so it
runs on every box.

  client.py mint <machine>      on the server box: a new token for that machine. The server keeps only its SHA-256, in
                                <secrets>/clients.json; the token is written to <secrets>/client-tokens/<machine>.token (0600)
                                for provisioning to carry to that box, and is never printed. Minting for the server box itself
                                also installs it as <secrets>/client.token and points <secrets>/client.url at the local port.
  client.py revoke <machine>    forget that machine's token
  client.py list                which machines hold a token (names and dates, nothing secret)
  client.py holds               the open items on hold that nothing holds now (no open after item, pane recycle, needs=external or
                                item-scoped anchor): item, mover, wake, who set it and when ("before the record" for a hold stored
                                before the server wrote one), one line each, so the item's mover can release them one by one
                                (update clear_hold=true). Reads only: nothing is released here. Exit 0 listed · 1 not reached.
  client.py get <read> [key]    registry | rules | brief | page-ts <page key | project id> | items <session> | project <id | page key | slug> | holds |
                                answer <board#N> (below) | for-you (below) | whoami | config | roles — read from the server with this machine's token (<secrets>/client.token);
                                config = the instance's non-secret settings;
                                roles = every session's role, {"generated": <UTC>, "sessions": {name: {role, project}}}; an agent
                                the project record holds whose page line is still owed is listed under its project like a page's, front
                                or back by its flag, with page_owed: true in its entry (no such key for a page's own agents);
                                project = one project's record, {id, key, keeper, agents: {name: {front, role, mandate_line}}}: its permanent
                                id (prj_<8 hex>), the page key it has now, the page's keeper and its agents (a name the page does not list
                                yet carries page_owed: true). Every API entry that takes a project takes the id or the key.
  client.py get answer <board#N>
                                {OWNER}'s answer on a board item, as one line: <kind> TAB <chosen option's label> TAB <his text> TAB <when>.
                                It is his newest decision on the item (kind decision: he answered it), even if he commented after it;
                                only when he has decided nothing, his newest comment (kind comment). A caller resumes only on a line
                                whose kind is decision, and keeps waiting on a comment. The label is empty when he picked none, the
                                text's line breaks are " / ", and <when> is when he gave it, an ISO time in the instance's timezone
                                (cut -f1, -f2, -f3, -f4 take it apart). The line does not say which question it answers: an item that was
                                answered before a question was filed on it returns that old answer, so
                                a caller files a fresh item for each question (client.py post question). Prints nothing and exits 0 while he has not answered. Exit 1,
                                the reason on stderr and nothing on stdout: no id given (usage; the server's 400 for an empty key),
                                an id that names no item or is not an item id (404), no token on this machine (401) or a server that
                                is not reached ([0]). Older ids work.
  client.py get notice <id>     what the router did with a notice: the six hex characters a send to a project returns ("held for the router — the
                                router rules notice a1b2c3 …"). Prints the same lines as the get tool for a notice id: sender, when, project, a one-line
                                excerpt, the ruling (passed to whom, merged, held or dropped), reason, rule, item, who ruled it and when; or, for a notice
                                not ruled yet, that it is still held and when the router rules it. Exit 0 · 1 an id no routing log holds ([404] no notice
                                <id>), no id given, no token or not reached.
  client.py get for-you         the owner's For you list (what he should see: a close with his words on it, a decision asked of him, a done check
                                that can never pass, a due date within 24 h), as JSON:
                                {"generated": <ISO time, instance zone>, "rows": [...newest first...], "flags": {"board#N": "watch" | "mute"}}.
                                A row: {id, kind (closed | reopened | decision | check_failed | due), item ("board#N"), project, what (one line), url, urgent, ts (epoch), when (ISO), slacked}. `flags` are his own
                                Watch / Mute settings on items (an item with no flag is in neither); "watch" adds an item that is not watched by
                                default, "mute" stops rows for it. A row leaves the list when he marks it seen on the board. Reads only.
                                Exit 0 · 1 no token or not reached.
  client.py post project-agent <project> <name> --role <role> (--front | --back) --mandate "<one line>" [--sender <session id>]
                                ask to list a new agent of a project (<project> = its id, page key or bare slug). The server
                                accepts it only when the asking session, by its id, resolves through the fleet to the project's keeper
                                or to a front agent its page lists: the id is $CLAUDE_CODE_SESSION_ID (Claude Code sets it in every Bash
                                command) or --sender <transcript id | cse_ id>; a bare name is refused. That id is the session's own
                                word, as every client call's sender is: the machine token proves the machine, nothing proves the session.
                                One more caller: the fleet tool's New session form, which has no session. A call whose --sender is a label in the
                                server's [project_agent] form_senders (default: none) AND whose token is a machine in form_machines
                                (default: none) may list a new agent on any LISTED project, with or without agents (a hidden
                                project: 403, list it again first with post project-list). The name must still start with the project's name;
                                it never changes an agent already listed. The same label from another machine, or another label from that
                                machine, gets the rules above.
                                The agent is written to the project's agents map in the project record, with its mandate line, and then the page's
                                `agents:` block is written from the record (a project with no page of this instance's page store gets no page write):
                                there is no line the page still owes, so the reply carries "page_owed": false and "page_yaml": "", and a "mirror"
                                {state, key, note} that says whether the page was written ("failed": the record has the agent all the same, and the
                                project's next change writes the page again). Said again as it stands it changes nothing; the same name with another front or
                                mandate is a 409 (retire or rename it first). Exit 0 listed · 1 refused or not reached.
  client.py get projects --scope <scope|all> [--q <search text>]
                                the projects the fleet tool's New session form offers (the tool is the only reader, over this machine's token): JSON
                                {"scope", "q", "generated", "scopes": [...], "projects": [{id, key, title, name, scope, listed, hidden, listed_by,
                                keeper, main, agents: {name: {front, role, mandate_line, page_owed?}}, items_30d, status, retired}]}. The listed projects of the
                                scope (listed = it has agents, or a board item touched in the last 30 days, or it was made or listed again on
                                purpose; a sub-page such as projects/example/notes never is), listed first, by key; with --q, the hidden ones
                                of the scope (a retired project, page status archived | retired | closed | done | dropped | completed | merged, is never in it) whose key, name or page title holds the text (case-insensitive) follow, each with "hidden": true.
                                A hidden project is never deleted. A scope is a project's group, set on purpose (post project, post project-list
                                --scope) else derived: a key whose prefix [project_scopes.by_prefix] maps to a scope, else the page's org, else its tag, else the default scope. Exit 0 ·
                                1 a bad scope (400), no token or not reached.
  client.py post project --scope <scope> (--key <projects/slug> | --name <name> [--page <page key or link>] [--make-page true|false]) [--title <title>] [--sender <label>]
                                make a new project (project_verbs.create): its entry in the project record first (a new permanent id, the name, the scope, the
                                mark that lists it), then its page when it has one. A page is optional: with `--name` alone the project has no page and none is
                                made. `--key` is the New session form's own parameter: the project's page, made from the project template of the [pages]
                                template_page page (Part 2) unless `--make-page false`, and the name is the page's slug unless `--name` is given. `--page` is a
                                pointer (a page key of this instance, or a link to another knowledge base) and makes a page only with `--make-page true`.
                                Under [pages] flavor = "plain" (the default) a page is a markdown file written into the server's pages checkout (paths.brain);
                                it is not committed or pushed, the instance's own sync or the caller does that. Under "gbrain" it is written through the
                                gbrain CLI on the server box. Prints the server's JSON {"project": <the record, as get project>, "created": true,
                                "page": {key, state, display_name}, "page_yaml": "", "mirror": {state, key, note}, "note"}, exit 0. The record is right as soon
                                as the call returns: a page that could not be written is told in page.state and the note, and the project's next change writes it again.
                                Refused, reason on stderr, exit 1: a key outside the page dirs, or with a sub-path, or a slug that is not lowercase letters,
                                digits and dashes when a page is made (400); a page that exists, has sub-pages or is some project's, or a name some project
                                has (409: use post project-list); the record cannot be written (503). The project has no agent: add the first with
                                `post project-agent`: on a project made or listed again this way, the first agent may be registered by a caller whose --sender
                                is the label that made or listed it (within the hour, the keeper no live session). The project name follows the scope
                                (`<scope>-<slug>`) for a page key, else it is the `--name` given.
  client.py post project-list --key <id|key|slug> [--scope <scope>] [--sender <label>]
                                list a hidden project again: it is marked listed on purpose (and given the scope, when one is passed). Prints
                                {"project": <the record>, "changed": bool, "note"}, exit 0; a sub-page is refused (400, naming the page to
                                list), an unknown project (404), an ambiguous slug (400).
  client.py post project-agent-rename <project> <OLD> <NEW> [--sender <label>]
                                rename an agent's entry in the project's agents map in the project record (<project> = its id, page key or bare
                                slug), in place: the entry keeps its mandate text, its place in the map and its front or background side. The page's
                                `agents:` block is then written from the record (project_verbs.agent_rename), and the registry, projects.json and
                                roles.json follow.
                                It renames no session (the fleet tool's). Same gate as the New session form's calls: --sender must be a label in
                                the server's [project_agent] form_senders AND the token a machine in form_machines, else 403 (no default label:
                                pass it). NEW must start with the project's name and belong to no other project. Prints the server's JSON, exit 0:
                                {"project", "key", "result": "renamed" | "already renamed", "old", "new", "front", "role", "mandate", "note"}. "already
                                renamed" (200) = OLD is no longer listed and NEW is; the reply carries NEW's front, role and mandate so the caller
                                can check it is the entry it expects. Treat it as done only for a rename you started (a retry after a lost reply):
                                the server keeps no record of OLD, so a mistyped OLD with an existing NEW answers the same. Refused, reason on stderr, exit 1,
                                nothing changed: 409 "<NEW> is already listed on <page>" (OLD still is too) · 404 "<OLD> is not listed on <page>" ·
                                409 NEW belongs to another project, or is a pending agent here · 409 "a rename of <page> is in progress; try again"
                                (another rename of that page is inside gbrain) · 400 a missing field, a bad name, NEW without the project's
                                prefix (<project name>-), OLD and NEW the same, an ambiguous slug, a page that is not a hub · 403 not the form · 404 unknown project · 503 the record cannot be written.
                                A page that could not be written is told in the answer's "mirror" (state "failed") and the note: the record is right.
  client.py post project-agent-retire <project> <name> [--sender <label>]
                                sala retired a session: stackshot takes the agent off its project (<project> = its id, page key or bare slug). The
                                server takes the agent off the project's agents map in the project record (a pending entry of the name goes with it),
                                then writes the page's `agents:` block from the record and adds a timeline line to the page: "<name> retired; its line
                                removed from the agents map". A project with no page of this instance's page store gets no page write.
                                When that leaves the project with no agent (an empty agents map, none pending) and no open item, the project is
                                archived (the record's status first, then the page's `status:` line; the answer adds "archived": true and an
                                "archive_note"; the Projects page then lists the project under Archived). With open items left the project stays as it is and is archived by stackshot's own ten-minute
                                sweep once none is left, however they left (completed or handed to another project); a failed page write is told in
                                the note and does not fail the retire. Nothing more is asked of the caller.
                                Same gate as post project-agent-rename: --sender must be a label in the server's [project_agent] form_senders
                                (sala's: sala-retire) AND the token a machine in form_machines, else 403 (no default label: pass it).
                                Prints the server's JSON, exit 0: {"project", "key", "result", "agent", "note", ...} with
                                200 "line removed" = the agent was on the project's agents map and is off it, the page written from the record ·
                                200 "dropped" = the agent was only pending here: the pending entry is removed · 200 "not listed" (with a "reason") = the
                                agent is on the project's map nowhere and not pending: nothing was changed (a repeat call after a lost reply is this).
                                The answer carries "mirror" {state, key, note}: "failed" means the page was not written (the record is right; the project's
                                next change writes it). Refused, reason on stderr, exit 1: 404 unknown project · 400 a
                                missing field, a bad name, an ambiguous slug, a page that is not a hub · 403 not the form · 409 "a rename or retire of
                                <page> is in progress; try again" · 503 the record cannot be written.
  client.py post for-you-seen --id <row id | all> --sender <label>
  client.py post watch --item <board#N> --state <watch|mute|default> --sender <label>
                                the web server's two writes on the For you list (the fleet tool's web server): mark a row (or every row) seen, and set an
                                item's Watch / Mute / Default. Both are refused (403) unless `--sender` is a label in the server's
                                [project_agent] form_senders (default: none) AND the token is a machine in form_machines (default: none),
                                the same check as the New session form's: a session holding the machine token may not clear his list or mute
                                his items. There is no default sender: pass the label. Prints the server's JSON, exit 0: for-you-seen
                                {"ok", "seen": [ids marked], "rows": [the unseen rows, as get for-you]} (404 a row not on the list); watch
                                {"ok", "item": "board#N", "state", "flags": {the whole map, as get for-you}} (404 an unknown item, 400 a bad
                                state). Exit 1 and the reason on stderr when refused or not reached.
  client.py post state ...      retired: an item stores alive or waiting directly now, so no call sets or clears a state. It prints the refusal (exit 1) that names what to pass through update instead:
                                mover=<who moves it>, hold=true with wake and wait_basis for a park, after=["board#N"] for another item, wait_kind with wait_event, ask_by and post_wake_mover for a wait on something
                                outside, needs=["decision"] with ask for {OWNER}'s call, step=<one line, no command> for his own step. `get items` carries each item's `state` and `state_fields` {carry field: text} when
                                an older item still stores a state, and neither when it stores none (the word an item reads as is not sent: its `list` and `get`'s model line say where it stands). It carries each item's `list` too: the home page's list the item is in, "your-move", "agents" or "waiting", so the items sheet groups as the page does.
  client.py post question --project <key|id|slug> --ask "<ask line>" --subject "<subject>" --request-id <token>
                                [--option "<label>=<line>" ...] [--recommended <label>] [--sender <label>]
                                for a script that has hit a question only {OWNER} can answer: file it as an open board item that needs
                                his decision, and print its id. The question's text is read from stdin and becomes the item's
                                description, one "- " bullet per line (each clipped as it reads to [description] line_max characters, and a line empty after its marker skipped), followed by the
                                bullet "- Filed by <label> (a script on <machine>)", which the item page and
                                the GitHub issue show {OWNER}. More lines than the description takes
                                ([description] max_lines, less that one) or more than 8000 characters is refused (exit 1) and the
                                script shortens it. The item
                                is owned by the project's front agent (its -main agent first; refused when the project lists none), filed
                                under the project's page, with needs = decision, the ask (`Decide: ... · Recommend: ... · Stakes: ... ·
                                By: ...`, one line) and the options (--option "label=line", 2 to 6 of them, repeated; --recommended
                                names the label of the one recommended, which is then required). --subject is required: the item's subject,
                                which must start with one of the instance's subject prefixes (e.g. [alpha] or [beta]: the
                                project's own; there is no default, since a question filed under the wrong prefix lands in the wrong
                                place on the board); omitted, the call is refused and the refusal names the prefixes; a subject over [subject] max_length (80, the prefix counted) is cut to it, not refused: write the action and its object, the rest in the description. <label> = the script's own name (default client.py); the
                                item records "<label> (a script on <machine>)" as its creator, as `message --sender` does. The server
                                runs the create tool's own checks (subject prefix, ask form, options, one decision per ask, project
                                page, page debt, GitHub mirror), so it refuses what the tool would, with the tool's text. Prints exactly
                                the new item's id (board#N) on stdout, exit 0; the reason on stderr, exit 1, when refused (400 a check of the
                                tool, 404 no such project, 409 no front agent), not reached ([0]) or when the project record cannot be read
                                right now (503, nothing filed).
                                --request-id is required, and makes the call safe to
                                repeat: the server remembers (machine, sender, request id) -> item, and the same triple again prints the
                                same item id, exit 0, and files nothing, however the first call ended for the caller (a timeout after the
                                item was filed, a retry). If that item has since been removed, the call files a new one. the fleet tool passes one
                                per parked question (the same token every time that question is filed again) and the same --sender. A
                                different sender, machine or token is a different question.
                                Read the answer with `client.py get answer <id>`; file a fresh item per question.
  client.py post terminal-prompt open --session <name|id> --question "<one line>" --sender <label>
  client.py post terminal-prompt clear --session <name|id> --sender <label>
                                for sala: a pane waits in its terminal for an answer (a question to {OWNER}, a guarded file, plan mode) that no hook can give.
                                open files one open item per session, in {OWNER}'s Your move list, and prints its id (exit 0): the subject "<session> is
                                waiting for your answer in its terminal", p1, mover {OWNER}, with the step "Answer <session>'s question in its
                                terminal", next "{OWNER}: open <the pane's address> and answer: `<question>`" (the address is [client] session_view with the
                                name, else the words "the pane of <name>"; the question stands as a code span, a backtick in it an apostrophe, and a line
                                over [metadata.next] line_max has the question cut at a word with an ellipsis), filed under the session's project from the sala
                                registry (else the [terminal] fallback_project page), the owner's answer, then its -main agent (the item's `then`), marked metadata.terminal_prompt = the session's name.
                                The question is one line of at most 200 characters (refused otherwise). A second open for a session that has an open item
                                changes its question and files nothing (prints the same id). clear closes the session's open item (outcome done, reason "the
                                pane stopped waiting"); with none open it does nothing and exits 0, printing nothing. --session is a name, an old name, a sala
                                id or a transcript id: the registry resolves it, so all reach one item. --sender (required) is the script's own label; the item
                                records "<label> via a script on <machine>". The row owes no page and tells no session (it is a notification, and it opens and
                                closes with the pane). The server runs the create tool's own checks (subject prefix, description and next gates, project page,
                                GitHub mirror), except the guard on alarming words, which does not judge a pane's own question. Exit 0 · 1 and the reason on
                                stderr when refused (400 a check, 409 no project with a front agent to file under), not reached ([0]) or misused (usage).
  client.py post job-gap open <timer> <code> --repo <owner/name> [--detail "<text>"] [--sender <label>]
  client.py post job-gap clear <timer> <code> [--sender <label>]
                                for sala's job-gap watcher: a timer or service of a machine has a gap (<code> = no-description | no-lane | bad-lane | not-git |
                                git-differs; <timer> = the unit's name) or the gap is fixed. open files ONE open item per (timer, code) and prints its id (exit 0): the subject
                                "<prefix> <timer>: <the gap>" (the project scope's prefix, else [subject] fallback_prefix; cut to [subject] max_length), p2, filed under the project page that owns --repo (the repository that holds the job's
                                script: [job_gap.repos] maps "owner/name" to the page, default none; an instance maps its own repos; any other repo is refused with a 400 that names the known ones), moved by the project's builder (its background agent
                                whose mandate builds; it is told once, at the create, and is in needs), the project's -main agent its creator (no front agent is woken),
                                next "<builder>: put <timer>'s unit file in <repo> with an X-Model-Lane= line, linked from there" (the fix for the code), the description bullets
                                say the gap and the fix (--detail, at most 600 characters, adds the watcher's own line), marked metadata.job_gap = "<timer>: <code>". A project
                                with no builder moves the item by its -main agent: the item and a line on stderr say so (exit 0). A repeat open of an open (timer, code) changes
                                nothing and prints the same id. clear closes the open item (outcome done, reason within [close] reason_max, the end state in outcome_text, the description unchanged)
                                and prints its id; with none open it does nothing, prints "no open item" on stderr and exits 0. --sender is the script's own label
                                (default client.py; sala-unit-gaps): at most 80 characters on one line, never the owner's name (the terminal prompt's gate); the item records
                                "<label> via a script on <machine>". The row owes no page. The server runs the create tool's own checks (subject prefix, description and next gates,
                                project page, GitHub mirror), except the guard on alarming words. Exit 0 · 1 and the reason on stderr when refused (400 a check, 409 no front agent
                                to file under), not reached ([0]) or misused (usage).
  client.py message <to> <text> --sender <label>
                                for a script: send a message the way a session's `message` tool does. <to> = a session's
                                name or id, or a page key (projects/<slug>), which reaches that project (its router rules
                                it) and is recorded in its routing log; <text> = the message, or - to read it from stdin; <label> =
                                the script's own name (nightly-job, size-watch). Exit 0 delivered or queued · 1 refused or failed.
                                --release green --pr <PR url> (release.sh after a clean deploy): to a pilot project's page, the
                                result is logged, not delivered, and ruled merged by `stackshot (auto)`; the open items anchored
                                to the PR get a comment, and it stays on the routing page.
                                Only with --sender release and a PR of the server checkout's own repository; any
                                other sender or PR, --release red, or none, is delivered as before. Exit 0 logged too.
  client.py recycled [--kind recycle|reboot] [--since <epoch>] [--flag-at <epoch>] [--result ok|partial] [--skipped "<names>"]
                                the fleet tool's end-of-recycle hook, called once per cleared recycle flag: the panes on
                                this machine were relaunched, so the server takes the waits-for-recycle field off the open items
                                that flag covered and tells their owners. --flag-at = the flag's time: an item flagged at or
                                before it is covered, one flagged after it stays (omitted: --since decides, as before). With
                                [client] recycle_env_prefix set, each flag defaults to <prefix>KIND / STARTED / FLAG_AT / RESULT /
                                SKIPPED from the environment, so the hook line needs none; unset, only the flags count.
                                Prints one line; exit 0 whatever happened.
  client.py recycle-wanted      the fleet tool's watchdog: prints "<count> <id>[@<epoch>][~<repo>:pr<N>]…", the open items not on
                                hold that a recycle of this machine would serve now. @<epoch> is the whole second the recycle was
                                asked for; ~<repo>:pr<N> is the pull request anchored to the item (its latest), which the fleet
                                tool waits to see live before it recycles; either is left out when the item has none. Prints
                                nothing when the server cannot be asked. Exit 0 whatever happened.
  client.py puller-lag          the fleet tool's watchdog: one line "<hostname> <reported> <current>" per box
                                whose puller reports a VERSION behind puller.py's; nothing when every box is current or the
                                server cannot be asked. Reads only. Exit 0 whatever happened.
  client.py recycle-due --item <id> | --pr <PR url>
                                for a script: mark a recycle of this machine's panes as due on an existing open item, as a
                                session would with update(recycle=true): the item by id, or the open items whose anchors include
                                that pull request (release.sh does this after a deploy whose session pick is a recycle). It never files an item:
                                when none covers the change, run [fleet] recycle_when_idle "<reason>" if one is set. Running it again changes
                                nothing. One line per item. Exit 0 marked (or already) · 1 refused or not reached.
  client.py released --pr <PR url> --sha <merge commit> [--dry-run]
                                for release.sh, once main's full run passed on a released merge and it recorded it as last-good: the
                                server settles the open items built for that pull request. Refused, with nothing written, when the PR is not
                                merged, --sha is missing or holds no merge of it, or the merge is not in the last-good commit and the
                                checkout's HEAD (a main run still going, a rollback). A PR of another repository counts only when the
                                server's [released.repos] lists it (else refused, naming the ones it lists): its merge must then be an
                                ancestor of that repository's checkout HEAD (it has no last-good). Only a release step counts: one that says it releases
                                the PR ("release PR #N", "release #N", or "release" before the PR's URL; never "not release", "don't release"
                                or "pre-release"), on an item anchored to the PR or naming its URL. A step is a pure release only when
                                nothing follows the release phrase or only a short parenthetical naming nothing to do ("(in its turn)",
                                "(after #7)"); anything else after it ("and verify the pages", ", restart x", " - check prod", "(needs an
                                ok)") is a follow-up: nothing ticked, nothing closed, the mover told once. A step that only mentions the PR
                                (investigate, review, verify, another repository's PR) is never ticked and never closes the item. An item whose
                                only open steps are that release is completed, outcome done, by the server, with no session turn; an item
                                with any other open step gets the release step ticked done and its mover one real notice ("PR #N is live; its
                                step is ticked; the item's other open steps remain"; none when every other open step is a release of another
                                PR), stamped on the item so a rerun never sends a second. Items on hold, whose needs name a decision
                                or a session other than the mover, or completed are left alone, each with why. --dry-run prints what it
                                would do and writes nothing. One line per item. Exit 0 · 1 refused or not reached.
  client.py sweep-released [--dry-run]
                                once, by hand: the same rule for every pull request whose merge is in the last-good commit and in the
                                checkout's HEAD. --dry-run lists what it would close, tick and tell, and writes nothing.
                                Exit 0 · 1 refused or not reached.
  client.py event --kind recycle|fleet_op|job_run [--machine M] [--verb V] [--name N] [--sessions N] [--result R] [--text "<what happened>"]
                                a fleet script reports an event an item may wait on (an event wait: update(wait_kind="event",
                                wait_event="fleet_op many", ask_by=<backstop day>)). The server turns every open item whose event wait this
                                one ends to its post-wake mover with what happened, and prints the items it woke. fleet_op needs --verb (the
                                op: lane, provision, update, recycle …) and reports --sessions (how many sessions the op covered; "fleet_op
                                many" waits for an op over more than one); job_run needs --name; --machine is the token's when left off. The
                                fleet tool posts one fleet_op report at the end of every op; nothing posts job_run yet. A
                                recycle (client.py recycled) and a PR's release (client.py released) are reported by their own hooks.
                                Exit 0 reported · 1 refused or not reached.
  client.py sweep-step-proof [--dry-run]
                                once, by hand (the server also does it every couple of minutes): every open step that names the event which
                                finishes it (`release PR #N`, `merge PR #N`, or a step_proof on the item) whose event has happened (the pull
                                request is merged, or merged and live with main's tests passed) is ticked by the server, its mover told what
                                the next step is, the item closed when no step is left; a step with a follow-up, or a condition, is not
                                ticked and its mover is told once. --dry-run lists what it would do and writes nothing. One line per item.
                                Exit 0 · 1 refused or not reached.
  client.py backfill-contact [--apply]
                                once, by hand: every open item without a live contact (the front agent the owner talks to about it) gets one, the
                                creator when that was a front agent, else the project's -main agent; an item whose contact is no front agent any
                                more falls to the -main agent too. Without --apply it is a dry run: it lists what it would set and the counts by
                                rule, and writes nothing. Exit 0 · 1 refused or not reached. (tools/backfill_contact.py is the dry run on a copy.)
  client.py setup-result --ok | --failed --step "<step name>" [--reason "<short text>"]
                                for a machine's provisioning script: report how its setup run ended. The server keeps the latest
                                result for this machine (the token's); a failed run shows on the machine's column of the board's
                                Machines panel, with the step named. Prints one line. Exit 0 recorded · 1 refused or not reached.
  client.py register            a session's SessionStart hook: tell the server this session exists (the hook's JSON on stdin
                                names it; its name, Remote Control link and version come from the CLI's own registry)
  client.py seen                its Stop hook: a sign of life (the hook's JSON on stdin)
  client.py drain               its UserPromptSubmit hook on a machine with no puller: print what waits in the server's inbox
                                for this session, so it reaches the session with the prompt, and confirm it
                                The three hook verbs never fail a hook: they answer within a few seconds and exit 0 whatever
                                happened, printing only what the session should read.

The server's address: $STACKSHOT_URL, else <secrets>/client.url (one line), else [client] url in stackshot.toml.
The machine's fetcher is puller.py, next to this file."""
import datetime, getpass, glob, hashlib, json, os, secrets, socket, sys, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import config as _cfg
import retired_inputs as _retired

SECRETS = str(_cfg.secrets())
CLIENTS = os.path.join(SECRETS, "clients.json")
TOKENS = os.path.join(SECRETS, "client-tokens")
TOKEN = os.path.join(SECRETS, "client.token")
URLF = os.path.join(SECRETS, "client.url")
READS = ("registry", "rules", "brief", "page-ts", "items", "item-facts", "holds", "whoami", "config", "recycle-wanted", "puller-lag", "roles", "project", "projects", "answer", "notice", "for-you")


def _write_private(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(text)
    os.replace(tmp, path)


def _clients() -> dict:
    try: return json.load(open(CLIENTS, encoding="utf-8"))
    except Exception: return {}


def mint(machine: str) -> str:
    """A fresh token for `machine` (replacing any earlier one). → the path of the file that holds it."""
    machine = machine.strip()
    if not machine or not all(c.isalnum() or c in "-_." for c in machine): raise ValueError("machine = its fleet name (letters, digits, - _ .)")
    tok = secrets.token_urlsafe(32)
    d = _clients(); d[machine] = {"sha256": hashlib.sha256(tok.encode()).hexdigest(), "created": datetime.datetime.now(_cfg.tz()).isoformat(timespec="seconds")}
    _write_private(CLIENTS, json.dumps(d, indent=1) + "\n")
    path = os.path.join(TOKENS, machine + ".token"); _write_private(path, tok + "\n")
    if machine == socket.gethostname():                 # the server box is its own first client
        _write_private(TOKEN, tok + "\n")
        _write_private(URLF, f"http://{_cfg.get('server', 'host') or '127.0.0.1'}:{_cfg.get('server', 'port') or 8020}\n")
    return path


def revoke(machine: str) -> bool:
    d = _clients()
    if machine not in d: return False
    del d[machine]; _write_private(CLIENTS, json.dumps(d, indent=1) + "\n")
    try: os.remove(os.path.join(TOKENS, machine + ".token"))
    except FileNotFoundError: pass
    return True


def server_url() -> str:
    u = os.environ.get("STACKSHOT_URL", "").strip()
    if not u:
        try: u = open(URLF, encoding="utf-8").read().strip()
        except Exception: u = ""
    return (u or str(_cfg.get("client", "url") or "")).rstrip("/")


def get(what: str, key: str = "", timeout: float = 10.0, **extra: str) -> tuple[int, str]:
    """One read from the server with this machine's token → (HTTP status, body). 0 = the server could not be reached. `extra`:
    further query parameters (item-facts' ids)."""
    if what not in READS: return 404, "no such read: " + " | ".join(READS)
    try: tok = open(TOKEN, encoding="utf-8").read().strip()
    except Exception: return 401, f"no token on this machine ({TOKEN}): mint one on the server box and provision it"
    q = {**({"key": key} if key else {}), **{k: v for k, v in extra.items() if v}}
    url = f"{server_url()}/client/{what}" + ("?" + urllib.parse.urlencode(q) if q else "")
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok, "User-Agent": "stackshot-client"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e: return e.code, e.read().decode("utf-8", "replace")
    except Exception as e: return 0, f"{type(e).__name__}: {str(e)[:160]}"


def post(what: str, body: dict, timeout: float = 20.0):
    """One write to the server with this machine's token → (HTTP status, the decoded JSON answer, or the text when it is not
    JSON). 0 = the server could not be reached."""
    try: tok = open(TOKEN, encoding="utf-8").read().strip()
    except Exception: return 401, f"no token on this machine ({TOKEN}): mint one on the server box and provision it"
    req = urllib.request.Request(f"{server_url()}/client/{what}", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json", "User-Agent": "stackshot-client"})
    def dec(raw: bytes):
        try: return json.loads(raw.decode("utf-8", "replace"))
        except Exception: return raw.decode("utf-8", "replace")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, dec(r.read())
    except urllib.error.HTTPError as e: return e.code, dec(e.read())
    except Exception as e: return 0, f"{type(e).__name__}: {str(e)[:160]}"


def held_for(uuid: str, name: str = "", timeout: float = 3.0) -> tuple[str, list[str]]:
    """The notices the server held for this session while it was busy (held.py) → (the text to put in front of its turn, the ids to acknowledge),
    ("", []) when none or when the server cannot be reached. The server leases the lines it returns and offers them again if they are not acknowledged (held_ack): at least
    once, never lost. A UserPromptSubmit hook (pages.py nag) prints the text, then acknowledges."""
    if not uuid: return "", []
    status, d = post("held", {"uuid": uuid, "name": name}, timeout)
    if status != 200 or not isinstance(d, dict): return "", []
    ids = d.get("ids")
    return str(d.get("text") or ""), [str(x) for x in ids] if isinstance(ids, list) else []


def held_ack(uuid: str, ids: list[str], timeout: float = 3.0) -> bool:
    """The hook printed these held lines: tell the server to remove them. False when it could not be told (the lines are offered again after their lease)."""
    if not uuid or not ids: return False
    status, _d = post("held", {"uuid": uuid, "ack": list(ids)}, timeout)
    return status == 200


def message(to: str, text: str, sender: str, timeout: float = 130.0, release: str = "", pr: str = "", fyi: bool = False) -> tuple[int, str]:
    """Send a message through the server with this machine's token → (HTTP status, the server's answer or its refusal).
    0 = the server could not be reached. The server delivers before it answers, which can take seconds. `release` = green
    (release.sh's result after a clean deploy; `pr` its PR's URL): the server logs it in the project's routing log and rules it
    itself instead of delivering it (it stays on the routing page); any other value is delivered as before."""
    body = {"to": to, "text": text, "sender": sender}
    if release: body["release"] = release
    if pr: body["pr"] = pr
    if fyi: body["fyi"] = True
    status, d = post("message", body, timeout)
    return status, (str(d.get("result") or d.get("error") or d) if isinstance(d, dict) else str(d))


def page_debt(run: str, deadline: float | None = None, timeout: float = 600.0) -> tuple[int, dict]:
    """The audit run's pages stage (audit_run.py): ask the server to make its page-debt pass for the audit run `run` (its start stamp), none begun after the epoch
    `deadline` → (HTTP status, {"enabled", "mode", "counts"} or {"error"}). 0 = the server could not be reached. The server makes the calls before it answers (one
    per page with debts that moved to its keeper), so `timeout` is the whole stage's. Not a command: a script calls it."""
    body: dict = {"run": run}
    if deadline is not None: body["deadline"] = deadline
    status, d = post("page-debt", body, timeout)
    return status, (d if isinstance(d, dict) else {"error": str(d)})


def orphan_handover(apply: bool = False, timeout: float = 120.0) -> tuple[int, dict]:
    """The audit's check of open items whose mover is gone (successor.py): ask the server for the hand-over to the closest live agent → (HTTP status, {"checked", "mode", "applied", "read", "found", "moved", "left",
    "skipped", "over_cap", "note"} or {"error"}). A dry run (nothing written, nobody told) unless `apply`. 0 = the server could not be reached. Not a command: audit_run.py and `audit.py orphans` call it."""
    status, d = post("orphan-handover", {"apply": bool(apply)}, timeout)
    return status, (d if isinstance(d, dict) else {"error": str(d)})


def recycled(argv: list[str], timeout: float = 20.0) -> int:
    """The fleet tool's end-of-recycle hook: report the recycle to the server and print its answer in one line. Always 0: the
    hook runs detached and must never fail a recycle. The flags win; with [client] recycle_env_prefix set, a flag not given
    is read from <prefix>KIND, STARTED, FLAG_AT, RESULT and SKIPPED in the environment (the stackshot–sala contracts). sala calls it once
    per cleared recycle flag (interface 4, contract version 19): flag_at, the flag's time, goes in the body when given and is left
    out when not (an older sala sends none)."""
    pfx = str(_cfg.get("client", "recycle_env_prefix") or "").strip()
    env = {"kind": "KIND", "since": "STARTED", "flag_at": "FLAG_AT", "result": "RESULT", "skipped": "SKIPPED"}
    v = {k: os.environ.get(pfx + e, "") if pfx else "" for k, e in env.items()}
    a = list(argv)
    for k in env:
        fl = "--" + k.replace("_", "-")
        if fl in a:
            i = a.index(fl); v[k] = a[i + 1] if i + 1 < len(a) else ""
    try: since = float(v["since"] or 0)
    except ValueError: since = 0.0
    try: flag_at = float(v["flag_at"] or 0)
    except ValueError: flag_at = 0.0
    body = {"kind": v["kind"] or "recycle", "started": since, "result": v["result"] or "ok", "skipped": v["skipped"].split()}
    if flag_at > 0: body["flag_at"] = flag_at
    status, d = post("recycled", body, timeout)
    if status == 200 and isinstance(d, dict):
        kept = d.get("kept") or []
        print(f"stackshot: {len(d.get('cleared') or [])} item(s) no longer wait for a recycle ({' '.join(d.get('cleared') or []) or 'none'})"
              + (f"; {len(kept)} kept ({', '.join(x.get('item', '') + ': ' + x.get('why', '') for x in kept)})" if kept else ""))
    else:
        print(f"stackshot: recycle not reported [{status}] {d if not isinstance(d, dict) else d.get('error') or d}"[:300])
    return 0


def recycle_due(argv: list[str], timeout: float = 30.0) -> int:
    """A script marks a recycle as due on an existing item (recycle-due; it never files one) → exit 0
    marked or already, 1 otherwise."""
    a, opt = list(argv), {}
    for k in ("item", "pr"):
        if "--" + k in a:
            i = a.index("--" + k)
            if i + 1 >= len(a): print(f"usage: --{k} needs a value"); return 1
            opt[k] = a[i + 1]; del a[i:i + 2]
    if a or len(opt) != 1:
        idle = " ".join(_cfg.recycle_when_idle())
        print('usage: client.py recycle-due --item <id> | --pr <PR url>' + (f'   (with no item to flag: {idle} "<reason>")' if idle else "")); return 1
    status, d = post("recycle-due", opt, timeout)
    if status != 200 or not isinstance(d, dict):
        print(f"stackshot: recycle not marked [{status}] {d.get('error') if isinstance(d, dict) else d}"[:600]); return 1
    for x in d.get("items") or []:
        print(f"stackshot: {x.get('item')} (mover {x.get('owner') or '?'}" + (f", anchored to {d['pr']}" if d.get("pr") else "") + ") "
              + ("already waits for a recycle" if x.get("action") == "already" else "now waits for a recycle")
              + (" — but it is on hold, so the watchdog does not count it until it wakes" if x.get("held") else ""))
    return 0


RELEASED_USAGE = "usage: client.py released --pr <PR url> --sha <merge commit> [--dry-run]  (the PR is of this repository, or of one the server's [released.repos] lists)"
SWEEP_RELEASED_USAGE = "usage: client.py sweep-released [--dry-run]"


def _released_lines(d: dict, dry: bool) -> list[str]:
    """One line per item the server settled (or, with --dry-run, would settle)."""
    out = []
    for x in d.get("items") or []:
        ref = x.get("ref") or (f"PR #{x['pr']}" if x.get("pr") else "PR")
        pr = f"{ref}: " if x.get("pr") else ""
        head = f"stackshot: {pr}{'would ' if dry else ''}"
        merged = x.get("kind") == "pr_merged"
        what = {"closed": ("close" if dry else "closed") + f" {x.get('item')} (outcome done: {x.get('reason') or ''})",
                "ticked": ("tick" if dry else "ticked") + f" the {'merge' if merged else 'release'} step of {x.get('item')}" + (" (every other open step " + ("waits on another pull request: " if merged else "releases another PR: ") + ("nobody to be told)" if dry else "nobody told)") if x.get("quiet")
                          else " and " + ("tell" if dry else "told") + f" its mover {x.get('told') or x.get('mover') or '(none)'} that the item's other open steps remain"),
                "told": (("tell" if dry else "told") + f" the mover {x.get('told') or x.get('mover') or '(none)'} of {x.get('item')} that {ref} was closed without being merged, so its step can never be ticked by it ({x.get('step') or 'the step'})") if x.get("dead")
                        else ("tell" if dry else "told") + f" the mover {x.get('told') or x.get('mover') or '(none)'} of {x.get('item')} that the PR is {'merged' if merged else 'live'} and its {'merge' if merged else 'release'} step is not ticked (it names a follow-up or a condition, so the step stays open)",
                "left": f"leave {x.get('item')} alone: {x.get('why')}" if dry else f"left {x.get('item')} alone: {x.get('why')}"}.get(str(x.get("action")), f"{x.get('action')} {x.get('item')}")
        out.append(f"{head}{what} — {x.get('subject') or ''}"[:400])
    return out or ["stackshot: no open item has a release step for " + (f"PR {d.get('pr')}" if d.get("pr") else "a pull request that is live")]


def released(argv: list[str], timeout: float = 60.0) -> int:
    """release.sh, after main's tests passed on a released merge: the server settles the items built for that PR → exit 0, 1 refused or not reached."""
    a = list(argv); dry = "--dry-run" in a
    a = [x for x in a if x != "--dry-run"]
    opt = _opts(a, ("pr", "sha"), RELEASED_USAGE)
    if opt is None or not opt.get("pr") or not opt.get("sha"):
        if opt is not None: print(RELEASED_USAGE, file=sys.stderr)
        return 1
    status, d = post("released", {**opt, "dry_run": dry}, timeout)
    if status != 200 or not isinstance(d, dict):
        print(f"stackshot: items not settled [{status}] {d.get('error') if isinstance(d, dict) else d}"[:600]); return 1
    print("\n".join(_released_lines(d, dry)))
    return 0


EVENT_USAGE = ("usage: client.py event --kind recycle|fleet_op|job_run [--machine M] [--verb V] [--name N] [--sessions N] [--result R] [--text \"<what happened>\"]"
               " (fleet_op needs --verb, job_run needs --name)")


def event(argv: list[str], timeout: float = 30.0) -> int:
    """A fleet script reports an event that an event wait waits on → exit 0 (the items woken are printed), 1 refused or not reached."""
    opt = _opts(list(argv), ("kind", "machine", "verb", "name", "sessions", "result", "text"), EVENT_USAGE)
    if opt is None or not opt.get("kind"):
        if opt is not None: print(EVENT_USAGE, file=sys.stderr)
        return 1
    status, d = post("event", opt, timeout)
    if status != 200 or not isinstance(d, dict):
        print(f"stackshot: event not reported [{status}] {d.get('error') if isinstance(d, dict) else d}"[:600]); return 1
    woke = d.get("woken") or []
    print(f"stackshot: {d.get('event') or 'event reported'}; " + (f"woke {', '.join(str(x) for x in woke)}" if woke else "no item was waiting on it"))
    return 0


BACKFILL_CONTACT_USAGE = "usage: client.py backfill-contact [--apply]"


def backfill_contact(argv: list[str], timeout: float = 180.0) -> int:
    """By hand: fill in the contact of every open item that has none (a dry run unless --apply) → exit 0, 1 refused or not reached."""
    a = list(argv); apply_ = "--apply" in a
    a = [x for x in a if x != "--apply"]
    opt = _opts(a, (), BACKFILL_CONTACT_USAGE)
    if opt is None:
        return 1
    status, d = post("backfill-contact", {**opt, "apply": apply_}, timeout)
    if status != 200 or not isinstance(d, dict):
        print(f"stackshot: backfill not run [{status}] {d.get('error') if isinstance(d, dict) else d}"[:600]); return 1
    print("stackshot: " + ("applied" if apply_ else "dry run (nothing written)") + ": " + ", ".join(f"{k} {v}" for k, v in (d.get("counts") or {}).items()))
    for r in d.get("items") or []:
        print(f"{r.get('item')}  {r.get('rule')}  {r.get('was') or '-'} → {r.get('to') or '-'}  ({r.get('project')})")
    if apply_:
        print(f"stackshot: {d.get('written', 0)} item(s) written")
    return 0


def sweep_released(argv: list[str], timeout: float = 120.0) -> int:
    """By hand, once: the released rule for the PRs the running server already holds → exit 0, 1 refused or not reached."""
    a = list(argv); dry = "--dry-run" in a
    a = [x for x in a if x != "--dry-run"]
    opt = _opts(a, (), SWEEP_RELEASED_USAGE)
    if opt is None:
        return 1
    status, d = post("sweep-released", {**opt, "dry_run": dry}, timeout)
    if status != 200 or not isinstance(d, dict):
        print(f"stackshot: sweep not run [{status}] {d.get('error') if isinstance(d, dict) else d}"[:600]); return 1
    print(f"stackshot: last-good {str(d.get('good') or '')[:7]}, live checkout {str(d.get('head') or '')[:7]}" + (" (dry run: nothing written, nobody told)" if dry else ""))
    print("\n".join(_released_lines(d, dry)))
    return 0


SWEEP_STEP_PROOF_USAGE = "usage: client.py sweep-step-proof [--dry-run]"


def sweep_step_proof(argv: list[str], timeout: float = 180.0) -> int:
    """By hand: settle every open step whose proof (a PR merged or released) has happened → exit 0, 1 refused or not reached."""
    a = list(argv); dry = "--dry-run" in a
    a = [x for x in a if x != "--dry-run"]
    opt = _opts(a, (), SWEEP_STEP_PROOF_USAGE)
    if opt is None:
        return 1
    status, d = post("sweep-step-proof", {**opt, "dry_run": dry}, timeout)
    if status != 200 or not isinstance(d, dict):
        print(f"stackshot: sweep not run [{status}] {d.get('error') if isinstance(d, dict) else d}"[:600]); return 1
    print(f"stackshot: last-good {str(d.get('good') or '')[:7]}, live checkout {str(d.get('head') or '')[:7]}" + (" (dry run: nothing written, nobody told)" if dry else ""))
    print("\n".join(_released_lines(d, dry)))
    return 0


PROJECT_AGENT_USAGE = 'usage: client.py post project-agent <project> <name> --role <role> (--front | --back) --mandate "<one line>" [--sender <session id>]'


def project_agent(argv: list[str], timeout: float = 30.0) -> int:
    """List a new agent of a project → exit 0 recorded, 1 refused, not reached or misused. The server allows the
    project's keeper and its front agents, told by the asking session's id: --sender, else $CLAUDE_CODE_SESSION_ID. Also allowed: the fleet tool's New
    session form (a --sender label in the server's [project_agent] form_senders, sent from a machine in form_machines), on any listed project."""
    a, opt = list(argv), {}
    for k in ("role", "mandate", "sender"):
        if "--" + k in a:
            i = a.index("--" + k)
            if i + 1 >= len(a): print(f"--{k} needs a value\n{PROJECT_AGENT_USAGE}"); return 1
            opt[k] = a[i + 1]; del a[i:i + 2]
    flags = [x for x in a if x in ("--front", "--back")]
    a = [x for x in a if x not in ("--front", "--back")]
    sender = (opt.get("sender") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "").strip()
    if len(a) != 2 or len(flags) != 1 or not opt.get("role", "").strip() or not opt.get("mandate", "").strip():
        print(PROJECT_AGENT_USAGE); return 1
    if not sender: print("no asking session: pass --sender <transcript id | cse_ id>, or run it where $CLAUDE_CODE_SESSION_ID is set (a name is not accepted)"); return 1
    status, d = post("project-agent", {"project": a[0], "name": a[1], "role": opt["role"], "front": flags[0] == "--front", "mandate": opt["mandate"], "sender": sender}, timeout)
    if status != 200 or not isinstance(d, dict):
        print(f"stackshot: agent not listed [{status}] {d.get('error') if isinstance(d, dict) else d}"[:700]); return 1
    print(d.get("note") or f"recorded {a[1]} in {d.get('project')}"); return 0


def _opts(argv: list[str], names: tuple[str, ...], usage: str) -> dict | None:
    """Cut `--name value` pairs out of argv → {name: value}; None (the usage on stderr) when a value is missing or anything else is left."""
    a, opt = list(argv), {}
    for k in names:
        if "--" + k in a:
            i = a.index("--" + k)
            if i + 1 >= len(a): print(f"--{k} needs a value\n{usage}", file=sys.stderr); return None
            opt[k] = a[i + 1]; del a[i:i + 2]
    if a: print(usage, file=sys.stderr); return None
    return opt


PROJECTS_USAGE = "usage: client.py get projects --scope <scope|all> [--q <search text>]"
PROJECT_NEW_USAGE = "usage: client.py post project --scope <scope> (--key <projects/slug> | --name <name> [--page <page key or link>] [--make-page true|false]) [--title <title>] [--sender <label>]"
PROJECT_LIST_USAGE = "usage: client.py post project-list --key <id | page key | slug> [--scope <scope>] [--sender <label>]"


def projects(argv: list[str], timeout: float = 20.0) -> int:
    """`get projects --scope S [--q TEXT]`: the New session form's project picker, as the server's JSON on stdout → exit 0; 1 and the reason on
    stderr when refused or not reached."""
    opt = _opts(argv, ("scope", "q"), PROJECTS_USAGE)
    if opt is None or not opt.get("scope", "").strip():
        if opt is not None: print(PROJECTS_USAGE, file=sys.stderr)
        return 1
    status, body = get("projects", timeout=timeout, scope=opt["scope"].strip(), q=opt.get("q", "").strip())
    if status != 200: print(f"stackshot: projects not read [{status}] {body}"[:700], file=sys.stderr); return 1
    print(body.rstrip()); return 0


def _post_json(what: str, body: dict, verb: str, timeout: float = 90.0, ok: tuple[int, ...] = (200,)) -> int:
    status, d = post(what, body, timeout)
    if status not in ok or not isinstance(d, dict):
        print(f"stackshot: {verb} [{status}] {d.get('error') if isinstance(d, dict) else d}"[:900], file=sys.stderr); return 1
    print(json.dumps(d, ensure_ascii=False)); return 0


def project_new(argv: list[str]) -> int:
    """`post project --scope S (--key K | --name N [--page P] [--make-page B]) [--title T] [--sender L]`: make a project in the record, and its page when it has one of this instance's page store and one
    is asked for (a file under plain pages, a gbrain page under gbrain) → the server's JSON on stdout, exit 0."""
    opt = _opts(argv, ("key", "name", "page", "make-page", "scope", "title", "sender"), PROJECT_NEW_USAGE)
    if opt is None or not opt.get("scope", "").strip() or not (opt.get("key", "").strip() or opt.get("name", "").strip()):
        if opt is not None: print(PROJECT_NEW_USAGE, file=sys.stderr)
        return 1
    body = {k: v for k, v in opt.items() if v.strip() and k != "make-page"}
    if opt.get("make-page", "").strip():
        mp = opt["make-page"].strip().lower()
        if mp not in ("true", "false"): print(f"--make-page = true | false\n{PROJECT_NEW_USAGE}", file=sys.stderr); return 1
        body["make_page"] = mp == "true"
    return _post_json("project", body, "project not made", 300.0)    # a gbrain write can take minutes


def project_list(argv: list[str]) -> int:
    """`post project-list --key K [--scope S] [--sender L]`: list a hidden project again → the server's JSON on stdout, exit 0."""
    opt = _opts(argv, ("key", "scope", "sender"), PROJECT_LIST_USAGE)
    if opt is None or not opt.get("key", "").strip():
        if opt is not None: print(PROJECT_LIST_USAGE, file=sys.stderr)
        return 1
    return _post_json("project-list", {k: v for k, v in opt.items() if v.strip()}, "project not listed", 30.0)


PROJECT_AGENT_RENAME_USAGE = "usage: client.py post project-agent-rename <project> <OLD> <NEW> [--sender <label>]"


def project_agent_rename(argv: list[str]) -> int:
    """`post project-agent-rename <project> <OLD> <NEW> [--sender L]`: rename an agent's entry on the project's page in place → the server's
    JSON on stdout, exit 0 (renamed, or already renamed); 1 and the reason on stderr when refused, not reached or misused."""
    a, opt = list(argv), {}
    if "--sender" in a:
        i = a.index("--sender")
        if i + 1 >= len(a): print(f"--sender needs a value\n{PROJECT_AGENT_RENAME_USAGE}", file=sys.stderr); return 1
        opt["sender"] = a[i + 1]; del a[i:i + 2]
    if len(a) != 3 or not all(x.strip() for x in a) or any(x.startswith("--") for x in a):
        print(PROJECT_AGENT_RENAME_USAGE, file=sys.stderr); return 1
    body = {"project": a[0].strip(), "old": a[1].strip(), "new": a[2].strip()}
    if opt.get("sender", "").strip(): body["sender"] = opt["sender"].strip()
    return _post_json("project-agent-rename", body, "agent not renamed", 300.0)     # gbrain reads, writes and reads back the page (up to 120 s each), as post project waits


PROJECT_AGENT_RETIRE_USAGE = "usage: client.py post project-agent-retire <project> <name> [--sender <label>]"


def project_agent_retire(argv: list[str]) -> int:
    """`post project-agent-retire <project> <name> [--sender L]`: sala retired a session; stackshot removes its line from the project page's agents map
    and adds a timeline line there (or drops the agent's pending entry); the project is archived when that leaves it no agent and no open item (stackshot's sweep does it later
    when open items are left) → the server's JSON on stdout, exit 0 (200 line removed, dropped or not listed);
    1 and the reason on stderr when refused, not reached or misused."""
    a, opt = list(argv), {}
    if "--sender" in a:
        i = a.index("--sender")
        if i + 1 >= len(a): print(f"--sender needs a value\n{PROJECT_AGENT_RETIRE_USAGE}", file=sys.stderr); return 1
        opt["sender"] = a[i + 1]; del a[i:i + 2]
    if len(a) != 2 or not all(x.strip() for x in a) or any(x.startswith("--") for x in a):
        print(PROJECT_AGENT_RETIRE_USAGE, file=sys.stderr); return 1
    body = {"project": a[0].strip(), "name": a[1].strip()}
    if opt.get("sender", "").strip(): body["sender"] = opt["sender"].strip()
    return _post_json("project-agent-retire", body, "agent not retired", 300.0)     # gbrain reads, writes and reads back the page, then adds the timeline line (up to 120 s each)


FORYOU_SEEN_USAGE = "usage: client.py post for-you-seen --id <row id | all> --sender <label>"
WATCH_USAGE = "usage: client.py post watch --item <board#N> --state <watch|mute|default> --sender <label>"


def for_you_seen(argv: list[str]) -> int:
    """`post for-you-seen --id <n|all> --sender L`: the web server marks a row (or all) seen → the server's JSON on stdout, exit 0."""
    opt = _opts(argv, ("id", "sender"), FORYOU_SEEN_USAGE)
    if opt is None: return 1
    rid = opt.get("id", "").strip()
    if not (rid == "all" or (rid.isascii() and rid.isdigit())):
        print(FORYOU_SEEN_USAGE, file=sys.stderr); return 1
    body = {"id": rid if rid == "all" else int(rid)}
    if opt.get("sender", "").strip(): body["sender"] = opt["sender"].strip()
    return _post_json("for-you/seen", body, "not marked seen", 30.0)


def watch(argv: list[str]) -> int:
    """`post watch --item board#N --state S --sender L`: the web server sets an item's For you flag → the server's JSON on stdout, exit 0."""
    opt = _opts(argv, ("item", "state", "sender"), WATCH_USAGE)
    if opt is None: return 1
    item = opt.get("item", "").strip()
    if not item or "/" in item or not opt.get("state", "").strip():
        print(WATCH_USAGE, file=sys.stderr); return 1
    body = {"state": opt["state"].strip()}
    if opt.get("sender", "").strip(): body["sender"] = opt["sender"].strip()
    return _post_json("items/" + urllib.parse.quote(item, safe="") + "/watch", body, "flag not set", 30.0)


def state_set(argv: list[str]) -> int:
    """`post state ...`: retired (no state to set or clear), so nothing is sent: the refusal that names what update takes instead → stderr, exit 1."""
    print(_retired.client_refusal(_cfg.owner()), file=sys.stderr)
    return 1


QUESTION_USAGE = ('usage: client.py post question --project <key|id|slug> --ask "<ask line>" --subject "<subject>" --request-id <token> '
                  '[--option "<label>=<line>" ...] [--recommended <label>] [--sender <label>]   (the question on stdin)')


def question(argv: list[str], timeout: float = 60.0, text: str | None = None) -> int:
    """A script files a question for the owner as a needs=decision item (the text on stdin) -> exit 0 and the item's id on stdout; 1 and the
    reason on stderr when refused, not reached or misused."""
    a, opt, options = list(argv), {}, []
    for k in ("project", "ask", "sender", "subject", "recommended", "option", "request-id"):
        while "--" + k in a:
            i = a.index("--" + k)
            if i + 1 >= len(a): print(f"--{k} needs a value\n{QUESTION_USAGE}", file=sys.stderr); return 1
            if k == "option": options.append(a[i + 1])
            else: opt[k] = a[i + 1]
            del a[i:i + 2]
    if a or not opt.get("project", "").strip() or not opt.get("ask", "").strip() or not opt.get("request-id", "").strip():
        print(QUESTION_USAGE, file=sys.stderr); return 1
    opts = []
    for o in options:
        label, eq, line = o.partition("=")
        if not eq or not label.strip() or not line.strip():
            print(f'--option "{o[:60]}" is not <label>=<line>\n{QUESTION_USAGE}', file=sys.stderr); return 1
        opts.append({"label": label.strip(), "line": line.strip(), "recommended": False})
    rec = opt.get("recommended", "").strip()
    if rec:
        hit = [x for x in opts if x["label"].lower() == rec.lower()]
        if not hit: print(f'--recommended "{rec}" is none of the --option labels\n{QUESTION_USAGE}', file=sys.stderr); return 1
        hit[0]["recommended"] = True
    text = sys.stdin.read() if text is None else text
    if not text.strip(): print("the question's text is empty: write it on stdin\n" + QUESTION_USAGE, file=sys.stderr); return 1
    body = {"project": opt["project"], "ask": opt["ask"], "text": text, "sender": opt.get("sender", "").strip(), "subject": opt.get("subject", "").strip()}
    body["request_id"] = opt["request-id"].strip()
    if opts: body["options"] = opts
    status, d = post("question", body, timeout)
    if status != 200 or not isinstance(d, dict) or not d.get("item"):
        print(f"stackshot: question not filed [{status}] {d.get('error') if isinstance(d, dict) else d}"[:1200], file=sys.stderr); return 1
    print(d["item"]); return 0


TERMINAL_PROMPT_USAGE = ('usage: client.py post terminal-prompt open --session <name|id> --question "<one line, at most 200 characters>" --sender <label>\n'
                         '       client.py post terminal-prompt clear --session <name|id> --sender <label>')
TERMINAL_PROMPT_Q_MAX = 200


def terminal_prompt(argv: list[str], timeout: float = 60.0) -> int:
    """`post terminal-prompt open|clear --session S [--question Q] --sender L`: sala says a pane waits in its terminal (open: one item in the owner's Your move list, a second open
    for the session changes its question) or has stopped waiting (clear: the item closes, no item open is no error) -> exit 0 (open prints the item's id); 1 and the reason on
    stderr when refused, not reached or misused."""
    verb = argv[0] if argv else ""
    if verb not in ("open", "clear"): print(TERMINAL_PROMPT_USAGE, file=sys.stderr); return 1
    opt = _opts(argv[1:], ("session", "question", "sender") if verb == "open" else ("session", "sender"), TERMINAL_PROMPT_USAGE)
    if opt is None: return 1
    session, sender, question = opt.get("session", "").strip(), opt.get("sender", "").strip(), opt.get("question", "").strip()
    if not session or not sender or (verb == "open" and not question):
        print(TERMINAL_PROMPT_USAGE, file=sys.stderr); return 1
    if verb == "open" and ("\n" in question or "\r" in question):
        print("the question must be one line: shorten it, the pane has the rest\n" + TERMINAL_PROMPT_USAGE, file=sys.stderr); return 1
    if verb == "open" and len(question) > TERMINAL_PROMPT_Q_MAX:
        print(f"the question is {len(question)} characters and at most {TERMINAL_PROMPT_Q_MAX} are taken: shorten it, the pane has the rest\n" + TERMINAL_PROMPT_USAGE, file=sys.stderr); return 1
    body = {"action": verb, "session": session, "sender": sender}
    if verb == "open": body["question"] = question
    status, d = post("terminal-prompt", body, timeout)
    if status != 200 or not isinstance(d, dict):
        print(f"stackshot: terminal prompt not {'opened' if verb == 'open' else 'cleared'} [{status}] {d.get('error') if isinstance(d, dict) else d}"[:1200], file=sys.stderr); return 1
    if verb == "open": print(d.get("item") or ""); return 0 if d.get("item") else 1
    return 0


JOB_GAP_USAGE = ('usage: client.py post job-gap open <timer> <code> --repo <owner/name> [--detail "<text, at most 600 characters>"] [--sender <label>]\n'
                 '       client.py post job-gap clear <timer> <code> [--sender <label>]')
JOB_GAP_DETAIL_MAX = 600


def job_gap(argv: list[str], timeout: float = 60.0) -> int:
    """`post job-gap open <timer> <code> --repo R [--detail T] [--sender L]` / `clear <timer> <code> [--sender L]`: sala's job-gap watcher says a timer or service of the host has a gap
    (open: one board item per timer and code, moved by the builder of the repo's project; a repeat open answers the same item) or that the gap is fixed (clear: the item closes, none open is
    no error) -> exit 0 (open prints the item's id, clear the ids it closed); 1 and the reason on stderr when refused, not reached or misused."""
    verb = argv[0] if argv else ""
    if verb not in ("open", "clear"): print(JOB_GAP_USAGE, file=sys.stderr); return 1
    if len(argv) < 3 or argv[1].startswith("--") or argv[2].startswith("--"): print(JOB_GAP_USAGE, file=sys.stderr); return 1
    timer, code = argv[1].strip(), argv[2].strip()
    opt = _opts(argv[3:], ("repo", "detail", "sender") if verb == "open" else ("sender",), JOB_GAP_USAGE)
    if opt is None: return 1
    repo, detail, sender = opt.get("repo", "").strip(), opt.get("detail", "").strip(), opt.get("sender", "").strip()
    if not timer or not code or (verb == "open" and not repo):
        print(("--repo <owner/name> is required: the repository that holds the job's script\n" if verb == "open" and timer and code else "") + JOB_GAP_USAGE, file=sys.stderr); return 1
    if len(detail) > JOB_GAP_DETAIL_MAX:
        print(f"the detail is {len(detail)} characters and at most {JOB_GAP_DETAIL_MAX} are taken: shorten it\n" + JOB_GAP_USAGE, file=sys.stderr); return 1
    body = {"action": verb, "timer": timer, "code": code}
    if sender: body["sender"] = sender
    if verb == "open":
        body["repo"] = repo
        if detail: body["detail"] = detail
    status, d = post("job-gap", body, timeout)
    if status != 200 or not isinstance(d, dict):
        print(f"stackshot: job gap not {'opened' if verb == 'open' else 'cleared'} [{status}] {d.get('error') if isinstance(d, dict) else d}"[:1200], file=sys.stderr); return 1
    if verb == "open":
        if not d.get("item"): print("stackshot: job gap not opened [200] the server answered no item id", file=sys.stderr); return 1
        if d.get("fallback"): print(f"stackshot: {d.get('project')} lists no builder, so {d.get('item')} is with {d.get('mover')}, its front agent", file=sys.stderr)
        print(d["item"]); return 0
    for gid in d.get("cleared") or []: print(gid)
    if not d.get("cleared"): print(f"stackshot: {d.get('note') or 'no open item for that gap; nothing was closed'}", file=sys.stderr)
    return 0


def answer(item: str, timeout: float = 20.0) -> int:
    """The owner's latest board answer on an item, as the server's one line (<option label> TAB <text>) -> exit 0 (nothing printed while
    he has not answered), 1 when the item is not found, the server is not reached or the id is misused."""
    if not item.strip(): print("usage: client.py get answer <board#N>", file=sys.stderr); return 1
    status, body = get("answer", item.strip(), timeout)
    if status != 200: print(f"stackshot: no answer read [{status}] {body}"[:600], file=sys.stderr); return 1
    if body.strip(): print(body.rstrip("\n"))
    return 0


SETUP_USAGE = 'usage: client.py setup-result --ok | --failed --step "<step name>" [--reason "<short text>"]'


def setup_result(argv: list[str], timeout: float = 20.0) -> int:
    """A provisioning script reports its run's end → exit 0 recorded, 1 refused, not reached or misused."""
    a, opt = list(argv), {}
    for k in ("step", "reason"):
        if "--" + k in a:
            i = a.index("--" + k)
            if i + 1 >= len(a): print(f"--{k} needs a value\n{SETUP_USAGE}"); return 1
            opt[k] = a[i + 1]; del a[i:i + 2]
    flags = [x for x in a if x in ("--ok", "--failed")]
    if len(flags) != 1 or len(a) != 1 or (flags[0] == "--failed" and not opt.get("step", "").strip()):
        print(SETUP_USAGE); return 1
    ok = flags[0] == "--ok"
    status, d = post("setup-result", {"ok": ok, "step": "" if ok else opt.get("step", ""), "reason": opt.get("reason", "")}, timeout)
    if status != 200 or not isinstance(d, dict):
        print(f"stackshot: setup result not recorded [{status}] {d.get('error') if isinstance(d, dict) else d}"[:600]); return 1
    s = d.get("setup") or {}
    print(f"stackshot: setup result recorded for {d.get('machine')}: " + ("ok" if s.get("ok") else f"failed at {s.get('step')}"))
    return 0


# ---------------------------------------------------------------------------- the hooks' verbs
REGISTRY = os.path.join(os.path.expanduser("~"), ".claude", "sessions")     # the CLI's own registry of live sessions


def os_user() -> str:
    """This machine's OS username, lowercased: the CLI makes its placeholder session names from it ("demo-3f"), so the server
    can tell one by its shape. Empty when it cannot be found."""
    try: return getpass.getuser().strip().lower()
    except Exception: return ""


def _hook_session() -> dict:
    """The session a hook runs in: the hook's JSON on stdin names its transcript id; the CLI's registry adds the rest."""
    try: payload = json.loads(sys.stdin.read() or "{}")
    except Exception: payload = {}
    sid = str(payload.get("session_id") or payload.get("sessionId") or "").lower()
    out = {"uuid": sid, "user": os_user()}
    best = None
    for f in glob.glob(os.path.join(os.environ.get("STACKSHOT_CLI_REGISTRY") or REGISTRY, "*.json")):
        try: r = json.load(open(f, encoding="utf-8"))
        except Exception: continue
        if str(r.get("sessionId") or "").lower() == sid and (best is None or float(r.get("updatedAt") or 0) > float(best.get("updatedAt") or 0)): best = r
    if best:
        out.update({"name": str(best.get("name") or ""), "name_source": str(best.get("nameSource") or ""), "bridge": str(best.get("bridgeSessionId") or ""),
                    "cli": str(best.get("version") or ""), "status": str(best.get("status") or "")})
    return out


def hook(verb: str, timeout: float = 4.0) -> int:
    """register · seen · drain, called from a session's hooks. Always 0: a hook must never stall or fail a session because
    the server is away."""
    try:
        s = _hook_session()
        if not s.get("uuid"): return 0
        if verb == "register": post("register", s, timeout)
        elif verb == "seen": post("seen", {"uuid": s["uuid"]}, timeout)
        elif verb == "drain":
            status, d = post("drain", {"uuid": s["uuid"], "name": s.get("name", "")}, timeout)
            ids = []
            for x in (d.get("deliveries") or []) if status == 200 and isinstance(d, dict) else []:
                print(x.get("text") or ""); ids += x.get("ids") or []
            if ids: post("ack", {"delivered": ids, "failed": []}, timeout)
    except Exception:
        pass
    return 0


def _usage() -> str:
    """The module's usage text with the instance's owner named ({OWNER}) and, when the owner runs steps in PowerShell or in sala's Shell ([steps] owner_shell), where a command runs (@WHERE@)."""
    mode = _cfg.owner_shell_mode()
    host = str(_cfg.get("steps", "bash_host", default="") or "").strip()
    name = str(_cfg.get("steps", "shell_name", default="") or "").strip()
    never = "never a `! ` line, the pane form, which the server refuses"
    if mode == "sala-shell":
        place = "sala's Shell" + (f" (the session `{name}`)" if name else "")
        where = f" as typed in {place}, bash on {host or 'a Linux host'}, and `ssh <host> '<command>'` for another machine; he pastes there with Shift+Insert, not Ctrl+V; {never}"
    elif mode == "powershell":
        where = f' with where it runs ("In PowerShell: …", {host or "a Linux host"} as `ssh -t {host or "<host>"} \'<command>\'`; {never})'
    else:
        where = f" ({never})"
    return (__doc__ or "").replace("{OWNER}", _cfg.owner()).replace("@WHERE@", where)


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd in ("register", "seen", "drain"): return hook(cmd)
    if cmd == "recycle-wanted":
        try:
            status, body = get("recycle-wanted", timeout=8.0)
            if status == 200: print(body.strip())
        except Exception: pass
        return 0
    if cmd == "holds":
        status, body = get("holds")
        print(body.rstrip() if status == 200 else f"[{status}] {body}"); return 0 if status == 200 else 1
    if cmd == "puller-lag":
        try:
            status, body = get("puller-lag", timeout=8.0)
            if status == 200 and body.strip(): print(body.strip())
        except Exception: pass
        return 0
    if cmd == "recycled":
        try: return recycled(argv[2:])
        except Exception as e: print(f"stackshot: recycle not reported ({type(e).__name__})"); return 0
    if cmd == "recycle-due":
        try: return recycle_due(argv[2:])
        except Exception as e: print(f"stackshot: recycle not marked ({type(e).__name__}: {str(e)[:160]})"); return 1
    if cmd == "released":
        try: return released(argv[2:])
        except Exception as e: print(f"stackshot: items not settled ({type(e).__name__}: {str(e)[:160]})"); return 1
    if cmd == "event":
        try: return event(argv[2:])
        except Exception as e: print(f"stackshot: event not reported ({type(e).__name__}: {str(e)[:160]})"); return 1
    if cmd == "sweep-step-proof":
        try: return sweep_step_proof(argv[2:])
        except Exception as e: print(f"stackshot: sweep not run ({type(e).__name__}: {str(e)[:160]})"); return 1
    if cmd == "backfill-contact":
        try: return backfill_contact(argv[2:])
        except Exception as e: print(f"stackshot: backfill not run ({type(e).__name__}: {str(e)[:160]})"); return 1
    if cmd == "sweep-released":
        try: return sweep_released(argv[2:])
        except Exception as e: print(f"stackshot: sweep not run ({type(e).__name__}: {str(e)[:160]})"); return 1
    if cmd == "post" and len(argv) > 2 and argv[2] == "project-agent":
        try: return project_agent(argv[3:])
        except Exception as e: print(f"stackshot: agent not listed ({type(e).__name__}: {str(e)[:160]})"); return 1
    for verb, fn, what in (("project", project_new, "project not made"), ("project-list", project_list, "project not listed"),
                          ("project-agent-rename", project_agent_rename, "agent not renamed"), ("project-agent-retire", project_agent_retire, "agent not retired"), ("for-you-seen", for_you_seen, "not marked seen"), ("watch", watch, "flag not set")):
        if cmd == "post" and len(argv) > 2 and argv[2] == verb:
            try: return fn(argv[3:])
            except Exception as e: print(f"stackshot: {what} ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr); return 1
    if cmd == "get" and len(argv) > 2 and argv[2] == "projects":
        try: return projects(argv[3:])
        except Exception as e: print(f"stackshot: projects not read ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr); return 1
    if cmd == "post" and len(argv) > 2 and argv[2] == "state":
        try: return state_set(argv[3:])
        except Exception as e: print(f"stackshot: state not set ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr); return 1
    if cmd == "post" and len(argv) > 2 and argv[2] == "question":
        try: return question(argv[3:])
        except Exception as e: print(f"stackshot: question not filed ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr); return 1
    if cmd == "post" and len(argv) > 2 and argv[2] == "terminal-prompt":
        try: return terminal_prompt(argv[3:])
        except Exception as e: print(f"stackshot: terminal prompt not sent ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr); return 1
    if cmd == "post" and len(argv) > 2 and argv[2] == "job-gap":
        try: return job_gap(argv[3:])
        except Exception as e: print(f"stackshot: job gap not sent ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr); return 1
    if cmd == "get" and len(argv) > 2 and argv[2] == "answer":
        try: return answer(argv[3] if len(argv) > 3 else "")
        except Exception as e: print(f"stackshot: no answer read ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr); return 1
    if cmd == "setup-result":
        try: return setup_result(argv[2:])
        except Exception as e: print(f"stackshot: setup result not recorded ({type(e).__name__}: {str(e)[:160]})"); return 1
    if cmd == "message":
        a = argv[2:]
        opt = {}
        fyi = "--fyi" in a
        a = [x for x in a if x != "--fyi"]
        for f in ("--sender", "--release", "--pr"):
            opt[f] = a.pop(a.index(f) + 1) if f in a and a.index(f) + 1 < len(a) else ""
            a = [x for x in a if x != f]
        sender = opt["--sender"]
        if len(a) != 2 or not sender or opt["--release"] not in ("", "green", "red"):
            print("usage: client.py message <to> <text | -> --sender <label> [--fyi] [--release green|red --pr <PR url>]"); return 1
        text = sys.stdin.read() if a[1] == "-" else a[1]
        status, body = message(a[0], text, sender, release=opt["--release"], pr=opt["--pr"], fyi=fyi)
        print(body if status == 200 else f"[{status}] {body}"); return 0 if status == 200 else 1
    if cmd == "mint" and len(argv) > 2:
        try: path = mint(argv[2])
        except ValueError as e: print(e); return 1
        print(f"minted a token for {argv[2]} → {path} (0600; not shown). The server knows it at once."); return 0
    if cmd == "revoke" and len(argv) > 2:
        print("revoked" if revoke(argv[2]) else "no token for that machine"); return 0
    if cmd == "list":
        for name, v in sorted(_clients().items()): print(f"{name}  since {str(v.get('created', ''))[:16]}")
        return 0
    if cmd == "get" and len(argv) > 2:
        status, body = get(argv[2], argv[3] if len(argv) > 3 else "")
        print(body if status == 200 else f"[{status}] {body}"); return 0 if status == 200 else 1
    print(_usage()); return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
