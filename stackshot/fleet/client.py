"""client.py — one machine's half of stackshot (the design doc). Stdlib only, so it
runs on every box.

  client.py mint <machine>      on the server box: a new token for that machine. The server keeps only its SHA-256, in
                                <secrets>/clients.json; the token is written to <secrets>/client-tokens/<machine>.token (0600)
                                for provisioning to carry to that box, and is never printed. Minting for the server box itself
                                also installs it as <secrets>/client.token and points <secrets>/client.url at the local port.
  client.py revoke <machine>    forget that machine's token
  client.py list                which machines hold a token (names and dates, nothing secret)
  client.py keys list|approve <fingerprint>|revoke <fingerprint>
                                on the server box: the public keys callers registered for themselves (`POST /keys/enroll`, docs/client-contract.md,
                                *A caller's own key*). list: each key's state (pending | approved), its first 16 fingerprint characters, sender,
                                label and the board item raised for it. approve: a pending key becomes trusted for the whole New session form, under its sender label and every label that starts with it and a `-`.
                                revoke: delete the key, pending or approved (the passes it traded stop at once). A fingerprint is typed with at
                                least its first 8 characters, as many as name one key.
  client.py holds               the open parked items that nothing holds now (no open after item, pane recycle, needs=external or
                                item-scoped anchor): item, mover, wake, who set it and when ("before the record" for a park stored
                                before the server wrote one), one line each, so the item's mover can release them one by one
                                (update clear_hold=true). Reads only: nothing is released here. Exit 0 listed · 1 not reached.
  client.py get <read> [key]    registry | rules | brief | page-ts <page key | project id> | items <session> | involved <session> | item-record <id> | open-records <session> | anchors-record | projects-record | project <id | page key | slug> | holds |
                                answer <board#N> (below) | for-you (below) | your-move (below) | whoami | config | roles | state-files — read from the server with this machine's token (<secrets>/client.token);
                                config = the instance's non-secret settings;
                                roles = every session's role, {"generated": <UTC>, "sessions": {name: {role, project}}}; an agent
                                the project record holds whose page line is still owed is listed under its project like a page's, front
                                or back by its flag, with page_owed: true in its entry (no such key for a page's own agents);
                                state-files = the files a box that does not run the server reads from its own state folder, as one JSON object:
                                {host, generated, projects (projects.json), fleet ({letter: {machine, sessions}}), versions (site/versions.json),
                                advertised_commit}; one that is not there is null or "". The puller of such a box keeps them current when
                                `[client] mirror_server_state = true` (with roles.json from `roles`); a reader may also fetch it by hand;
                                project = one project's record, {id, key, keeper, keeper_agent, keeper_source, agents: {name: {front, role,
                                mandate_line, keeper?}}}: its permanent id (prj_<8 hex>), the page key it has now, the page's keeper and its
                                agents (a name the page does not list yet carries page_owed: true). The keeper is a mark on one agent:
                                `keeper: true` on that agent, set in the project record or by a `keeper: <agent>` line on the page (a sub-page can
                                carry a mark of its own, `page_keepers` on the record entry above it). keeper_agent
                                is that agent, else the project's builder, else its -main agent (a one-session page: its own session), and
                                keeper_source says which: mark, derived (no mark), split (a page a split made: it follows the page its
                                `split_from:` or `parent:` line names) or legacy (no mark, and the page's old name line or `agent:` names
                                the keeper; a sub-page or hub-linked page with a name line of its own stays legacy). Both are empty for a retired
                                project with no mark. With a mark, `keeper` is the marked agent too, except on a page a split made (source split): there
                                `keeper` stays what the page's old fields name, so `keeper_agent` is the answer and wins. A page with a
                                `split_from:` or `parent:` line also carries it as `split_from` (optional). Every API entry that takes a project takes the id or the key.
  client.py get answer <board#N>
                                {OWNER}'s answer on a board item, as one line: <kind> TAB <chosen option's label> TAB <his text> TAB <when>.
                                It is his newest decision on the item (kind decision: he answered it), even if he commented after it;
                                only when he has decided nothing, his newest comment (kind comment). A caller resumes only on a line
                                whose kind is decision, and keeps waiting on a comment. The label is empty when he picked none, the
                                text's line breaks are " / ", and <when> is when he gave it, an ISO time in the instance's timezone
                                (cut -f1, -f2, -f3, -f4 take it apart). On a board of several members, the text of an answer to a step
                                another member had a part in, which left the item on a step, opens with who answered, which step, and
                                who the step was with after that answer: one member's Done need not end the step.
                                The line does not say which question it answers: an item that was
                                answered before a question was filed on it returns that old answer, so
                                a caller files a fresh item for each question (client.py post question). Prints nothing and exits 0 while he has not answered. Exit 1,
                                the reason on stderr and nothing on stdout: no id given (usage; the server's 400 for an empty key),
                                an id that names no item or is not an item id (404), no token on this machine (401) or a server that
                                is not reached ([0]). Older ids work.
  client.py get notice <id>     what the router did with a notice: the six hex characters a send to a project returns ("held for the router — the
                                router rules notice a1b2c3 …"). Prints the same lines as the get tool for a notice id: sender, when, project, a one-line
                                excerpt, the ruling (passed to whom, merged, archived, held or dropped), reason, rule, item, who ruled it and when; or, for a notice
                                not ruled yet, that it is still held and when the router rules it. Exit 0 · 1 an id no routing log holds ([404] no notice
                                <id>), no id given, no token or not reached.
  client.py get for-you         the owner's For you list (what he should see: a close with his words on it, a decision asked of him, a done check
                                that can never pass, a due date within 24 h), as JSON:
                                {"generated": <ISO time, instance zone>, "rows": [...newest first...], "flags": {"board#N": "watch" | "mute"}}.
                                A row: {id, kind (closed | reopened | decision | check_failed | due), item ("board#N"), project, what (one line), url, urgent, ts (epoch), when (ISO), slacked}. `flags` are his own
                                Watch / Mute settings on items (an item with no flag is in neither); "watch" adds an item that is not watched by
                                default, "mute" stops rows for it. A row leaves the list when he marks it seen on the board. Reads only.
                                Exit 0 · 1 no token or not reached.
  client.py get involved <session>
                                the open items a session is the contact of or an observer on, whoever moves them, newest write first, as JSON: {"items": [{shown ("board#N"), subject, url (the item's page), mover (the name of whoever moves it now, as the item model reads it and `get item-facts` gives it),
                                contact (the item's contact now, by name), observers ([names]), list ("your-move" | "agents" | "waiting", as `get items` gives it), held (as `get items` gives it: true for a parked item, one that waits on an open item or a doing item waiting for a stated wake), until (the day a held item comes back,
                                "YYYY-MM-DD" as the home page's Waiting row dates it; null for an item that is not held or has no such day), state_updated and updated (epoch seconds, null for none), scope (the item's group: the scope of the board row its project's page rolls up to, one of the names in [project_scopes] order, the default one for an item with no project; `get items`, `get your-move` and `get item-facts` rows carry the same `scope`)}]}. <session> is read as `get items` reads it (a pane name, a transcript uuid, a cse_ id or a permanent id). A closed item is not in it; a session that is neither contact nor
                                observer anywhere, or that no one knows, gets {"items": []}; no session is 400. No cap. Reads only. Exit 0 · 1 no token, a refusal or not reached.
  client.py get your-move       every open item in {OWNER}'s Your move group, as JSON: {"items": [{shown ("board#N"), subject, url (the item's page), ask (the open ask line, "" for none), updated (epoch seconds
                                of the item's last write), scope}], "group": {"en": <the group's name>, "ko": <its name in the second language>}}. It is the home page's own list with no cap, in the home page's order (the item that has been his longest first; `get brief` shows the first
                                five lines of the same list), and holds every item whose mover is him, whichever session it names or whether it names one. An empty group is {"items": [], "group": {...}}.
                                `scope` is the name of the subsection the home page lists that item under (one of the names in [project_scopes] order; the default one for an item with no project).
                                `group` is the heading the home page draws over the list in each language, as the string table gives it; a language with no catalog on the install has the English text. Reads only.
                                Exit 0 · 1 no token or not reached.
  client.py post project-agent <project> <name> --role <role> (--front | --back) [--surface sala|slack] --mandate "<one line>" [--sender <session id | label>]
                                ask to list a new agent of a project (<project> = its id, page key or bare slug). --surface is where a front agent talks with him: sala (the
                                default, a session of sala's list) or slack (an agent that answers his Slack app messages: a front agent that is never the project's keeper, a background
                                agent or its -main agent, and that no router, audit or stall notice is addressed to); the role slack stands for it (`--role slack --front`), and
                                any other surface, or a slack agent with --back, is refused (400). The server
                                accepts it only when the asking session, by its id, resolves through the fleet to the agent marked as the project's keeper
                                or to a front agent its page lists: the id is $CLAUDE_CODE_SESSION_ID (Claude Code sets it in every Bash
                                command) or --sender <transcript id | cse_ id>; a bare name is refused. That id is the session's own
                                word, as every client call's sender is: the machine token proves the machine, nothing proves the session.
                                One more caller: the fleet tool's New session form, which has no session. A call whose --sender is a label in the
                                server's [project_agent] form_senders (default: none) AND whose token is a machine in form_machines
                                (default: none) may list a new agent on any LISTED project, with or without agents (a hidden
                                project: 403, list it again first with post project-list). The name must still start with the project's name;
                                it never changes an agent already listed. The same label from another machine, or another label from that
                                machine, gets the rules above.
                                A third caller: the fleet tool's timer, for a project with an open want for a background agent (a message reached it and it lists
                                none: `client.py background-wanted`). A BACKGROUND CALL has a --sender label in the server's [project_agent] bg_senders (default: none) AND
                                a token from a machine in bg_machines (default: none; when empty, form_machines), and lists a background agent only (--back, no slack surface) on a project whose want is
                                open right now: [background_agent] enabled on, the want recorded and not served, and no background agent listed yet. Anything else is 403,
                                and the reason names the condition that failed (the machine is not allowed, not a background agent, no open want: off, none recorded, served, a
                                background agent already, or a project that is hidden, retired or not a top-level project with a front agent). The name check, the clashes and the
                                listed and pending rules are the form's. It never changes an agent already listed, and opens nothing else: bg_senders gives no access to
                                project-agent-rename, -retire or -mandate, nor to the For you writes and the saved colors.
                                The agent is written to the project's agents map in the project record, with its mandate line, and then the page's
                                `agents:` block is written from the record (a project with no page of this instance's page store gets no page write):
                                there is no line the page still owes, so the reply carries "page_owed": false and "page_yaml": "", and a "mirror"
                                {state, key, note} that says whether the page was written ("failed": the record has the agent all the same, and the
                                project's next change writes the page again). Said again as it stands it changes nothing; the same name with another front or
                                mandate or surface is a 409 (retire or rename it first). Exit 0 listed · 1 refused or not reached.
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
  client.py get agent-name <project> <name> [<name> ...]
                                would `post project-agent` take each name as a new agent of the project? The same checks, as a read: nothing is
                                written, no --sender, no lock. Prints the server's JSON {"project", "key", "results": [{name, valid, code, reason}],
                                "first_free", "prefixes"}: one result per name in the order asked, `code` one of ok | format | prefix | clash | listed |
                                pending | hub | hidden | retired, `reason` the text the register gives for it (empty for ok), `first_free` the first name
                                that is valid (null when none is), `prefixes` what the project's names must start with. A name already listed on the project
                                is not valid (the register changes nothing for it only when side and mandate match); a name a pending entry holds is told held. At most
                                20 names, none with a comma. A hub page, a hidden project and a retired one answer with that code for every name.
                                Exit 0 when the call answers, even when every name is invalid · 1 an unknown or ambiguous project (404, 400),
                                a bad call, no token or not reached.
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
                                For a page that was made, the note carries one offer of the ready `anchors` call (the project's repository releases and its Slack channel; off with [anchors] offers = false).
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
  client.py post project-agent-mandate <project> <name> --mandate "<one line>" [--sender <session id>]
                                change the mandate line of an agent already listed on the project (<project> = its id, page key or bare slug);
                                `post project-agent` refuses another line for a listed name (409), and a hand edit of the page's line is not read
                                (the record wins, and the next page write restores it), so this is the way to change it. The server changes the line in
                                the project's agents map in the project record, then writes the page's `agents:` block from the record, so the page and
                                the record agree and the line stays. The agent keeps its side (front or background), its place in the map and who
                                listed it. Same gate as `post project-agent`: the asking session's id ($CLAUDE_CODE_SESSION_ID, or --sender
                                <transcript id | cse_ id>; a bare name is refused) must resolve to the agent marked as the project's keeper or a front agent its page lists;
                                the New session form's label does not apply. Prints the server's JSON, exit 0: {"project", "key", "agent": {name:
                                {front, role, mandate_line}}, "previous", "mirror" {state, key, note}, "note"}; the same line again is 200 "nothing
                                changed". "mirror" state "failed" = the page was not written (the record is right; the project's next change writes it); "retired" = the page is in a brain marked shared (or [pages] copy_project_lines is false) and gets no copy: read the record with `projects fields`.
                                Refused, reason on stderr, exit 1, nothing changed: 400 a missing field, a bad name, an empty line (to remove the agent use
                                post project-agent-retire), a line over 600 characters or with a control character or a backslash, an ambiguous slug, a page that is not
                                a hub · 403 a name as --sender, or a session that is neither the keeper mark's agent nor a front agent · 404 unknown project, or <name>
                                not listed (list it first with post project-agent) · 503 the record cannot be written.
  client.py post project-agent-rename <project> <OLD> <NEW> [--sender <label>]
                                rename an agent's entry in the project's agents map in the project record (<project> = its id, page key or bare
                                slug), in place: the entry keeps its mandate text, its place in the map and its front or background side. The page's
                                `agents:` block is then written from the record (project_verbs.agent_rename), and the registry, projects.json and
                                roles.json follow.
                                It renames no session (the fleet tool's). Same gate as the New session form's calls: --sender must be a label in
                                the server's [project_agent] form_senders AND the token a machine in form_machines, else 403 (no default label:
                                pass it; a background call's label in bg_senders does not count). NEW must start with the project's name and belong to no other project. Prints the server's JSON, exit 0:
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
                                (sala's: sala-retire) AND the token a machine in form_machines, else 403 (no default label: pass it; a background call's label in bg_senders does not count).
                                Prints the server's JSON, exit 0: {"project", "key", "result", "agent", "note", ...} with
                                200 "line removed" = the agent was on the project's agents map and is off it, the page written from the record (or the agent is the
                                project's own session, named by its page's display-name, on a one-session project with no agents map: its agents map is now empty) ·
                                200 "dropped" = the agent was only pending here: the pending entry is removed · 200 "not listed" (with a "reason") = the
                                agent is on the project's map nowhere and not pending: nothing was changed (a repeat call after a lost reply is this).
                                The answer carries "mirror" {state, key, note}: "failed" means the page was not written (the record is right; the project's
                                next change writes it), "retired" that the page gets no copy of the record (a shared brain, or [pages] copy_project_lines off). Refused, reason on stderr, exit 1: 404 unknown project · 400 a
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
                                mover=<who moves it>, until with wait_kind="time" and wait_basis for a park (within the wait cap's days a park needs his recorded words), after=["board#N"] for another item, wait_kind with wait_event, until and mover (who takes it then) for a wait on something
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
                                open files one open item per session, in {OWNER}'s Your move list, and prints its id (exit 0): the subject "Answer
                                <session> in its terminal", p1, mover {OWNER}, with the step "Answer <session>'s question in its
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
                                "<prefix> <the task>", as "Add X-Model-Lane= to <timer>" or "Put <timer> in git" (the project scope's prefix, else [subject] fallback_prefix; cut to [subject] max_length), p2, filed under the project page that owns --repo (the repository that holds the job's
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
  client.py post catch (- | --hook <name> --id <id> --t <ISO time with offset> --pane <session> --kind <kind> [--sender <raw sender>] [--outcome <text>] [--first <text>])
                                for a front agent's hook: a turn that signed off with a no-ask phrase after a turn a trigger started is one "catch" in the server's catch log. `-` reads the fields
                                as one JSON object on stdin ({"hook","id","t","pane","kind","sender","outcome","first"}, all text; a flag given as well wins). hook = the hook's name, id = the catch's own id
                                (a replay of an id with the same t is safe: it prints "duplicate" and writes nothing more), t = when it happened, ISO 8601 with an offset or Z (from Jan 1st 2020 to two days ahead), pane = the front agent that signed off, kind = how the
                                turn that began it was started (notice, message, script, ...), sender = that turn's raw sender, outcome = what the hook did, first = the first words of the reply (clipped to 200
                                characters). The server works out the source (router notice, stackshot message, background-agent hand-back, front peer, script, other), the project and the day in its own timezone; the first catch
                                of an hour for one pane and sender sends the project's builder one held word that starts no turn. Prints "ok" (or "duplicate") and exits 0; 1 and the reason on stderr when refused (400 a field), not
                                reached ([0]) or misused (usage). The counts per source and day are the audit's `catches` report.
  client.py post anchor-add -   for a plugin hook that has just seen a session make a pull request or an issue: add anchors to a project, or to some of its open items, the way the anchors tool's `add` does. `-` reads one JSON object on
                                stdin: {"project": "<key|slug>", "add": ["<pull request or issue URL>", ...], "items": ["<item id>", ...] (optional: with none the anchors are project-wide), "sender": "<the session or script>"}; project, add and sender are required.
                                The anchors tool's own checks all apply: a project that names no page, an item that is completed or belongs to another project is refused with the tool's text, and a URL that is not https://github.com/<owner>/<repo>/pull/<n> or /issues/<n> is refused (no other anchor shape is taken here). At most 10 URLs of 300 characters and 20 item ids a call; the sender is made one plain line of at most 80 characters. Adding only: the
                                route takes no removal (a `remove` key is refused). The anchor records "<sender> via a script on <machine>". Prints the server's text (the project's anchors, as the tool lists them) and exits 0; 1 and the reason on stderr
                                when refused (400), not reached ([0]) or misused (usage).
  client.py post agent-state --file <path>
                                for the fleet's session manager: push which registered agents are busy and which idle, the whole fleet in one JSON file that REPLACES the server's last snapshot
                                (`POST /client/agent-state`, machine token; the body is {"schema": 1, "written": <epoch s>, "agents": {<name>: {...}}}). The file's bytes go to the server exactly as they are
                                (never parsed or re-encoded here). A file that is missing, unreadable, not a regular file (a folder, a pipe, a device; a link to a regular file is read) or over 1,000,000 bytes is refused here with one line and exit 1, and nothing is sent; an empty --file value is a usage error. Prints the server's answer,
                                {"ok": true, "agents": N}, and exits 0; any other answer prints the server's one-line reason on stderr and exits 1, as does a server that is not reached ([0]), no token, or a misuse
                                (usage on stderr).
  client.py post machines --file <path>
                                for the fleet manager: post its machine list, which the server keeps as the last good list (`POST /client/machines`, machine token; the body is {"schema": 1, "written": <epoch s>,
                                "machines": [{"name", "hostname", "letter", "ssh", "addresses", "roles", "retired", "sources"}], "not_read": [<file name>]}; docs/client-contract.md has every limit). Post it when the list
                                changes and at least every few minutes: `written` is the list's age. `--file -` (or a bare `-`) reads the body from standard input. The file's bytes go to the server exactly as they are (never
                                parsed or re-encoded here). A file that is missing, unreadable, not a regular file or over 1,000,000 bytes is refused here with one line and exit 1, and nothing is sent. Prints the server's answer,
                                {"ok": true, "machines": N} (or {"ok": true, "kept": "newer"}: a list of an older `written` arrived late and the stored one stays), and exits 0; any other answer prints the server's one-line reason on
                                stderr and exits 1 (400 a body that does not fit, the last good list stays; 413 a body over the limit), as does a server that is not reached ([0]), no token, or a misuse (usage on stderr). Run it with STACKSHOT_CLIENT_PASS unset: the route takes the machine token only.
  client.py post item-open <marker> --project <key|id|slug> --subject "<action and object>" --mover <agent> --step "<agent>: <what it does>" --line "<fact>" [--line "<fact>" ...] [--sender <label>]
                                for a timer's script that finds work for a project's background agent (a project that lists none is a front-only project: the item is filed with its -main agent): open ONE board item for it and print its id (exit 0). <marker> = <kind>:<what> (for example
                                test_trim:stackshot), the item's mark: while an item with that marker is open on the same project a repeat call prints the same id and files nothing; once it is closed a call files a new item. A project holds at most 10 open items filed by this route: past it a new marker is refused until one closes. --mover must be a
                                background agent under `background:` on the project's page (refused otherwise, the refusal names the listed ones; a front-only project lists none, so the mover becomes its -main agent, named in no needs); it is named in needs and told once, at the create. --step is one line that starts
                                with the mover's name and a colon. --subject is the action and its object with no prefix: the server puts the project scope's prefix before it. Each --line is one fact, a "- " bullet of the
                                description (repeat it; at most [description] max_lines less one, each at most [description] line_max characters as a bullet; too many or too long is refused, never cut); the last bullet is
                                "- Opened by <label> (a script on a client machine)", so no host name reaches the item or its GitHub issue. --sender is the script's own label (default client.py): one word of at most 60 characters, never the owner's
                                name. The project's -main agent is the item's creator. The server runs the create tool's own checks (subject, description and next gates, project page, GitHub mirror) except the ones that judge a session's write: a description needs no Goal bullet, and the
                                row owes no page. Exit 0 · 1 and the reason on stderr when refused (400 a check, 404 no such project, 409 no front agent to file under), not reached ([0]), misused (usage) or when the project record cannot be
                                read right now (503, nothing filed).
  client.py post item-sync <marker> open --project <key|id|slug> --subject "<action and object>" --mover <the person> --then <agent> --step "<what the person does>" --line "<fact>" [--line "<fact>" ...] [--sender <label>]
  client.py post item-sync <marker> refresh --line "<fact>" [--line "<fact>" ...] [--sender <label>]
  client.py post item-sync <marker> close [--reason "<why>"] [--sender <label>]
                                for a timer's script that keeps ONE board item for the person in step with a condition it checks (open while the condition holds, closed when it is gone). Each call prints one line and exits 0:
                                "<item> opened", "<item> refreshed", "<item> closed", "<item> left open: open steps of others remain" (a close that found another writer's step open) or "no open item for <marker>; nothing was refreshed|closed" (a no-op, no error). <marker> = <kind>:<what> (for example
                                plugin_sync:stackshot), the item's mark and its only key: refresh and close carry no project, and reach only an item this route opened (a machine token can touch no other item through it). open files an item
                                whose mover is the person (--mover must be his name) and whose `then` is --then (an agent the project's page lists: it takes the item after his step), with --step as his one step (his name goes before it; one you wrote is not
                                doubled), under the project's -main agent as its creator, the state your-step, as the terminal prompt's row; --subject is the action and its object with no prefix (the server puts the project scope's prefix
                                before it); each --line is one fact, a "- " bullet of the description (repeat it; as for item-open: at most [description] max_lines less one, each at most [description] line_max characters, refused and never cut, and not judged by the Goal-first rule a session's description is; the last bullet
                                is "- Opened by <label> (a script on a client machine)"). While an item with the marker is open a repeat open is a refresh
                                (the description changes, never the subject) that may also set the sent step. Once he has finished or answered on the item (his Done, his note that names no later time, any step of his he marked done)
                                no repeat sets a step on it again, so a script with a version in its step does not bring it back; the close and a new item ask him again. Until then only a step that differs from the one the route last sent is set, so one a session replaced, reworded, dropped
                                or withdrew, is not asked again; a step a wait dropped before he answered it is asked again by the first repeat after the wait. No step is set while the item reads as waiting, while a decision ask to him is pending, for a
                                step of none, clear or - (a first open refuses those), or while an open line of his that is not the route's own stands, unless one of his open lines reads as the sent step: then the item is only made to ask it
                                when it asks him nothing, and a session's current step is never written over. A step not set for one of these reasons is set by a later open once the reason is gone. The route drops no line but its own, and an item that asked the one it drops asks the sent step instead. An item
                                filed before the route kept these records is read from its first step, the line its create wrote; where that line cannot be told from a session's, no newer step is set while a line of his stands.
                                Setting a step makes the person the mover again; a stored then stays, and with
                                none stored the agent that had the item becomes then (or the project's builder in a front agent's place). A repeat's --mover and --then are checked and never written themselves. A refused step changes nothing; the same marker on another project is refused. Once it is closed an open files
                                a new item. A project holds at most 10 open items of this route. refresh rewrites the description of the marker's open item and nothing else. close completes the open item as done through the update tool's own close
                                (--reason is one line, cut to [close] reason_max; the default says the script saw the condition gone), ticks his open steps and says so in the history, and leaves the item open (ticking nothing) while another writer's step is open on it (a script may refresh with a line saying the condition cleared; the close completes once the others are done, or the agent that holds the item completes it). --sender is the script's own label (default client.py): one word of at most 60
                                characters, never the person's name. The server files it through the create tool's own code (its subject and next gates, project page, GitHub mirror; the description's line count and length are the route's own pre-checks), and the row owes no page and tells no session. Exit 0 · 1 and the reason on stderr when
                                refused (400 a check, 404 no such project, 409 no front agent to file under), not reached ([0]), misused (usage) or when the project record cannot be read right now (503, nothing filed).
  client.py message <to> <text> --sender <label> [--fyi | --question]
                                for a script: send a message the way a session's `message` tool does. <to> = a session's
                                name or id, or a page key (projects/<slug>), which reaches that project (its router rules
                                it) and is recorded in its routing log; <text> = the message, or - to read it from stdin; <label> =
                                the script's own name (nightly-job, size-watch). Exit 0 delivered or queued · 1 refused or failed.
                                --question: a front agent asks the session it writes to something; only a reply to it is an
                                answer. Not with --fyi, and not in the owner's own name.
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
  client.py background-wanted   the fleet tool's timer: one line "<project key> <name prefix> <front agent>" per project whose
                                messages have no background agent to go to and that could use one (the agent is called
                                <name prefix>-<role>); nothing when none, when [background_agent] enabled is off or when the
                                server cannot be asked. Reads only. Exit 0 whatever happened. The timer lists the agent with `post project-agent --back`,
                                a background call (see there).
  client.py project-activity [--json]
                                for a script that decides whether a project is quiet: per project, when it last heard from outside and when
                                its owner last gave input. Plain output is one line per project, "<project key> <anchor> <owner>", each a
                                whole epoch second or - for none; --json prints {"projects": {"<project key>": {"anchor": <epoch|null>,
                                "owner": <epoch|null>}}}. anchor = the newest anchor notice from outside (an event on a watched thing; not
                                a board notice, a message, a routine event on the fleet's own repository, a log-only anchor or the hub's
                                own warning). owner = the newest of his board actions (an answer, decision, Done, note or comment on an
                                item, on the board or on its GitHub issue; not a step the server settled on a mail) and his front-chat
                                messages (the time he last typed in a front agent's pane; not a notice, a relayed message or a background
                                agent's pane). A sub-page counts for its project. Only projects with either time are listed; a project
                                not listed has had neither. Reads only. Exit 0 and the answer (nothing printed when no project has
                                either) · 1 and the reason on stderr when the server cannot be asked or refuses, so a script never reads
                                a failure as "no activity".
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
                                ancestor of that repository's checkout HEAD (it has no last-good; the server reads the checkout the entry
                                names, over ssh when it is on another machine). Only a release step counts: one that says it releases
                                the PR ("release PR #N", "release #N", or "release" before the PR's URL; never "not release", "don't release"
                                or "pre-release"), on an item anchored to the PR or naming its URL. A step is a pure release only when
                                nothing follows the release phrase or only a short parenthetical naming nothing to do ("(in its turn)",
                                "(after #7)"); anything else after it ("and verify the pages", ", restart x", " - check prod", "(needs an
                                ok)") is a follow-up: nothing ticked, nothing closed, the mover told once. A step that only mentions the PR
                                (investigate, review, verify, another repository's PR) is never ticked and never closes the item. An item whose
                                only open steps are that release is completed, outcome done, by the server, with no session turn; an item
                                with any other open step gets the release step ticked done and its mover one real notice ("PR #N is live; its
                                step is ticked; the item's other open steps remain"; none when every other open step is a release of another
                                PR), stamped on the item so a rerun never sends a second. Parked items, whose needs name a decision
                                or a session other than the mover, or completed are left alone, each with why. --dry-run prints what it
                                would do and writes nothing. One line per item. Exit 0 · 1 refused or not reached.
  client.py sweep-released [--dry-run]
                                once, by hand: the same rule for every pull request whose merge is in the last-good commit and in the
                                checkout's HEAD. --dry-run lists what it would close, tick and tell, and writes nothing.
                                Exit 0 · 1 refused or not reached.
  client.py event --kind recycle|fleet_op|job_run [--machine M] [--verb V] [--name N] [--sessions N] [--result R] [--text "<what happened>"]
                                a fleet script reports an event an item may wait on (an event wait: update(wait_kind="event",
                                wait_event="fleet_op many", until=<backstop day>)). The server turns every open item whose event wait this
                                one ends to its post-wake mover with what happened, and prints the items it woke. fleet_op needs --verb (the
                                op: lane, provision, update, recycle …) and reports --sessions (how many sessions the op covered; "fleet_op
                                many" waits for an op over more than one); job_run needs --name; --machine is the token's when left off. The
                                fleet tool posts one fleet_op report at the end of every op; nothing posts job_run yet. A
                                recycle (client.py recycled) and a PR's release (client.py released) are reported by their own hooks.
                                Exit 0 reported · 1 refused or not reached.
  client.py job-failed <unit> <host> <ISO-Z time of the failing run> <project>
  client.py job-ok <unit> <host> <ISO-Z time>
                                for a scheduled job's failure hook and its success hook (no --sender: the label is `job alert`). job-failed files ONE board item
                                per (unit, host) for the project's builder (<project> = a project page key, a `scope/project` label, or a single `-` when the unit has none; a `-` or
                                a project this server has no page for is filed under the builder of the general project [job_alert] fallback_project names, and the item says so; none set is refused), or, when that item is open, adds the
                                run's time to it and counts it; prints the item's id, exit 0. job-ok closes the open item of (unit, host) with the run's time as the reason;
                                with none open (or the success older than the item's latest failed run) it prints nothing and exits 0, and sending it twice closes once.
                                Exit 1 and the reason on stderr when refused, not reached or misused (usage): a caller that must not fail on it ignores the status,
                                and re-sends a job-ok that did not arrive.
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
  client.py repoint <from> <to> [--apply]
                                before a session is retired: hand what open items hold under its name to another listed session: mover, then, needs, observers, the open next lines that name it,
                                contact, and tell_him when <to> is a front agent. It also lists the settings and project marks that name <from>, which it does not edit. A new holder that is not a
                                front agent gets one notice. Without --apply it is a dry run: it writes nothing. Exit 0 · 1 refused, not reached or misused.
  client.py setup-result --ok | --failed --step "<step name>" [--reason "<short text>"]
                                for a machine's provisioning script: report how its setup run ended. The server keeps the latest
                                result for this machine (the token's); a failed run shows on the machine's column of the board's
                                Machines panel, with the step named. Prints one line. Exit 0 recorded · 1 refused or not reached.
  client.py post inbox-hold <key> [<key> ...] [--kind msg|hub] [--minutes N]
  client.py post inbox-release <key> [<key> ...] [--kind msg|hub]
                                hold a session's inbox so a line is not handed out while its pane is relaunched, and lift it: the keys are the session's transcript id
                                and its name; without --kind both sources (msg and hub) are named, as the file hold does. The server keeps these holds in a file of their
                                own and honors them together with the ones a tool on its box writes into held-<source>.txt. A hold lasts --minutes (above 0, at most 1440; 0 is refused; without it [client] inbox_hold_minutes,
                                10), and holding again refreshes it; one never released is taken out within a minute after its time is up. At most 500 keys are held at a time. A release lifts only holds made by this call: a key that is held in
                                another tool's file stays held and is named in `held_elsewhere`. Prints the server's JSON ({held, expires} or
                                {released, held_elsewhere?}). Exit 0 · 1 refused or not reached.
  client.py get item-record <id>
                                one item's stored record exactly as the board's file holds it, open or closed, nothing derived, with the anchors that name it: {"id": the store's id, "shown": "board#N", "record":
                                {subject, status, metadata: {steps, phase, mover, wait fields …}, …}, "anchors": [{url, items, added, by, page, pages}]}. 400 a bad id, 404 an id that names no item, 503 a file that does not read. Reads only.
  client.py get open-records <session>
                                the stored records of the open items a session moves, takes after an answer or is named on (the items of `get items`, each as `get item-record` gives it), in one call:
                                {"session", "total": how many open items it has, "truncated": true when the answer left some out (at most 300 records and about 4 MB), "unreadable": [ids of items whose file does not read], "items": [{id, shown, record, anchors}]}.
                                A closed item is not in it. 400 a bad key, 503 an anchors file that does not read. Reads only.
  client.py get anchors-record  the anchors map as the board's file holds it: {"anchors": {<project key>: [{url, items, added, by}]}, "truncated": true when a very large map was cut}; {} without a file, 503 when it does not read. Reads only.
  client.py get projects-record the project record alone, the value `get state-files` carries as `projects` (projects.json as the server publishes it, one JSON object), without that read's other files. 503 when it is not there or does not read. Reads only.
  client.py get inbox-holds [<key>]
                                what is held: {"holds": [{kind, key, origin (api | file | resume: which file holds it), since, expires}], "now"}, since and expires (epoch, null for none) only for a hold
                                made by post inbox-hold. With a key, that key's rows. Reads only.
  client.py get inbox-waiting <name>[,<transcript id>]
                                does a line wait in the server's inbox for that session (a line whose address, transcript id, name or permanent id is one of the keys),
                                held or not: {"keys", "hub": n, "msg": n, "waiting": bool, "held": {"hub", "msg"}}. Reads only.
  client.py register            a session's SessionStart hook: tell the server this session exists (the hook's JSON on stdin
                                names it; its name, Remote Control link and version come from the CLI's own registry)
  client.py seen                its Stop hook: a sign of life (the hook's JSON on stdin)
  client.py drain               its UserPromptSubmit hook on a machine with no puller: print what waits in the server's inbox
                                for this session, so it reaches the session with the prompt, and confirm it
                                The three hook verbs never fail a hook: they answer within a few seconds and exit 0 whatever
                                happened, printing only what the session should read.

The server's address: $STACKSHOT_URL, else <secrets>/client.url (one line), else [client] url in stackshot.toml.
Who the call is from: this machine's token (<secrets>/client.token), unless $STACKSHOT_CLIENT_PASS holds a value: then that value goes as the
Bearer of every get and post of that process instead, and the token file is not read. A caller with a key of its own (docs/client-contract.md, *A caller's
own key*) trades a signed claim at POST /keys/pass for a pass (ssp_...) and sets the variable for the New session form's calls (post project-agent,
project-agent-rename, project-agent-retire) only. The client sends the value as it is; the server decides what a pass opens, and refuses what it does not.
An unset or empty variable changes nothing. The value is never printed, logged or written to a file, and no error text of this client repeats it.
The machine's fetcher is puller.py, next to this file."""
import os as _os, sys as _sys
if not __package__:   # started as a script (python3 stackshot/<area>/<name>.py): the checkout must be importable
    _here = _os.path.dirname(_os.path.abspath(__file__))
    _sys.path[:] = [_os.path.dirname(_os.path.dirname(_here))] + [p for p in _sys.path if _os.path.abspath(p or ".") != _here]
import datetime, getpass, glob, hashlib, json, os, re, secrets, socket, stat, sys, urllib.error, urllib.parse, urllib.request

from stackshot.core import config as _cfg
from stackshot.core import retired_inputs as _retired

SECRETS = str(_cfg.secrets())
CLIENTS = os.path.join(SECRETS, "clients.json")
TOKENS = os.path.join(SECRETS, "client-tokens")
TOKEN = os.path.join(SECRETS, "client.token")
URLF = os.path.join(SECRETS, "client.url")
READS = ("registry", "rules", "brief", "page-ts", "items", "involved", "item-facts", "asks-named", "item-record", "open-records", "anchors-record", "projects-record", "holds", "whoami", "config", "recycle-wanted", "puller-lag", "background-wanted", "project-activity", "roles", "state-files", "project", "projects", "agent-name", "answer", "notice", "for-you", "your-move", "inbox-holds", "inbox-waiting")


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


PASS_ENV = "STACKSHOT_CLIENT_PASS"


def _pass() -> str:
    """The caller's pass from $STACKSHOT_CLIENT_PASS ("" when unset, empty or blanks): sent as the Bearer in place of the machine token. Held only in this process; never printed or written."""
    return os.environ.get(PASS_ENV, "").strip()


def _scrub(text: str, tok: str) -> str:
    """`text` with the pass taken out, as typed and as an exception's repr writes it: a value that is not a pass, or one the transport refused, never reaches an error text."""
    if not tok: return text
    for form in {tok, repr(tok)[1:-1], ascii(tok)[1:-1], repr(tok.encode("utf-8", "replace"))[2:-1]}:
        if form: text = text.replace(form, "<pass>")
    return text


def _fail(e: Exception, tok: str) -> str:
    """The text of a call that raised. With a pass in use only a network fault (an OSError) says more than its type, and its text has the pass taken out."""
    if tok and not isinstance(e, OSError): return f"{type(e).__name__}: detail withheld while {PASS_ENV} is in use"
    return f"{type(e).__name__}: {_scrub(str(e), tok)[:160]}"


def get(what: str, key: str = "", timeout: float = 10.0, **extra: str) -> tuple[int, str]:
    """One read from the server with this machine's token (or, when $STACKSHOT_CLIENT_PASS is set, with that pass) → (HTTP status, body). 0 = the server could not be reached. `extra`:
    further query parameters (item-facts' ids)."""
    if what not in READS: return 404, "no such read: " + " | ".join(READS)
    pas = _pass(); tok = pas
    if not pas:
        try: tok = open(TOKEN, encoding="utf-8").read().strip()
        except Exception: return 401, f"no token on this machine ({TOKEN}): mint one on the server box and provision it"
    q = {**({"key": key} if key else {}), **{k: v for k, v in extra.items() if v}}
    url = f"{server_url()}/client/{what}" + ("?" + urllib.parse.urlencode(q) if q else "")
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok, "User-Agent": "stackshot-client"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, _scrub(r.read().decode("utf-8", "replace"), pas)
    except urllib.error.HTTPError as e: return e.code, _scrub(e.read().decode("utf-8", "replace"), pas)
    except Exception as e: return 0, _fail(e, pas)


def post(what: str, body: dict, timeout: float = 20.0, raw: bytes | None = None):
    """One write to the server with this machine's token (or, when $STACKSHOT_CLIENT_PASS is set, with that pass) → (HTTP status, the decoded JSON answer, or the text when it is not
    JSON). 0 = the server could not be reached. `raw`: the body's bytes, sent exactly as they are in place of `body` (never parsed or encoded again)."""
    pas = _pass(); tok = pas
    if not pas:
        try: tok = open(TOKEN, encoding="utf-8").read().strip()
        except Exception: return 401, f"no token on this machine ({TOKEN}): mint one on the server box and provision it"
    req = urllib.request.Request(f"{server_url()}/client/{what}", data=json.dumps(body).encode() if raw is None else raw, method="POST",
                                 headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json", "User-Agent": "stackshot-client"})
    def dec(answer: bytes):
        text = _scrub(answer.decode("utf-8", "replace"), pas)
        try: return json.loads(text)
        except Exception: return text
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return r.status, dec(r.read())
    except urllib.error.HTTPError as e: return e.code, dec(e.read())
    except Exception as e: return 0, _fail(e, pas)


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


def message(to: str, text: str, sender: str, timeout: float = 130.0, release: str = "", pr: str = "", fyi: bool = False, question: bool = False) -> tuple[int, str]:
    """Send a message through the server with this machine's token → (HTTP status, the server's answer or its refusal).
    0 = the server could not be reached. The server delivers before it answers, which can take seconds. `release` = green
    (release.sh's result after a clean deploy; `pr` its PR's URL): the server logs it in the project's routing log and rules it
    itself instead of delivering it (it stays on the routing page); any other value is delivered as before. `fyi` = the message asks nothing: a background or a front agent gets it with its next turn
    and no turn of its own (a front agent needs no mark on the first line for it, as for a session's fyi). A front agent whose hook cannot fetch held lines does not get it:
    the server refuses (status 400), so the answer is a failure, never a delivery. `question` = a front agent asks the session it writes to something: only a reply to a message sent with it is an answer
    (the server refuses it beside `fyi` and from the owner's own name)."""
    body = {"to": to, "text": text, "sender": sender}
    if release: body["release"] = release
    if pr: body["pr"] = pr
    if fyi: body["fyi"] = True
    if question: body["question"] = True
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
              + (" — but it is parked, so the watchdog does not count it until it wakes" if x.get("held") else ""))
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


REPOINT_USAGE = "usage: client.py repoint <from> <to> [--apply]"


def repoint(argv: list[str], timeout: float = 180.0) -> int:
    """By hand: move what open items hold under one session's name to another (a dry run unless --apply) → exit 0, 1 refused, not reached or misused."""
    apply_ = "--apply" in argv
    names = [x for x in argv if x != "--apply"]
    if len(names) != 2 or any(x.startswith("-") for x in names):
        print(REPOINT_USAGE, file=sys.stderr); return 1
    status, d = post("repoint", {"from": names[0], "to": names[1], "apply": apply_}, timeout)
    if status != 200 or not isinstance(d, dict):
        print(f"stackshot: items not moved [{status}] {d.get('error') if isinstance(d, dict) else d}"[:600]); return 1
    items = d.get("items") or []
    print(f"stackshot: {'applied' if apply_ else 'dry run (nothing written)'}: {d.get('from')} to {d.get('to')}, {len(items)} open item(s) name it" + (f", {d.get('written', 0)} written" if apply_ else ""))
    for r in items:
        print(f"{r.get('item')}  ({r.get('project')})  {', '.join(r.get('changed') or []) or 'nothing to change'}" + "".join(f"  left: {x}" for x in r.get("left") or []))
    if d.get("created"):
        print(f"stackshot: {d['created']} open item(s) were created by {d.get('from')}; the creator is not changed")
    for s in d.get("settings") or []:
        print(f"still names it, not edited here: {s}")
    if d.get("told"):
        print(f"stackshot: {d.get('to')} is sent one notice for {len(d['told'])} item(s)")
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


PROJECT_AGENT_USAGE = ('usage: client.py post project-agent <project> <name> --role <role> (--front | --back) [--surface sala|slack] --mandate "<one line>" [--sender <session id | label>]'
                       '\n  --sender: the asking session\'s id (the keeper or a front agent); the New session form\'s label (form_senders) from its machine; or, with --back, the timer\'s label (bg_senders) for a project whose want is open')


def project_agent(argv: list[str], timeout: float = 30.0) -> int:
    """List a new agent of a project → exit 0 recorded, 1 refused, not reached or misused. The server allows the
    the agent marked as the project's keeper and its front agents, told by the asking session's id: --sender, else $CLAUDE_CODE_SESSION_ID. Also allowed: the fleet tool's New
    session form (a --sender label in the server's [project_agent] form_senders, sent from a machine in form_machines), on any listed project; and a background call, the fleet tool's timer
    listing a background agent (--back) for a project whose want is open (a --sender label in bg_senders, from a machine in bg_machines, else form_machines)."""
    a, opt = list(argv), {}
    for k in ("role", "mandate", "sender", "surface"):
        if "--" + k in a:
            i = a.index("--" + k)
            if i + 1 >= len(a): print(f"--{k} needs a value\n{PROJECT_AGENT_USAGE}"); return 1
            opt[k] = a[i + 1]; del a[i:i + 2]
    flags = [x for x in a if x in ("--front", "--back")]
    a = [x for x in a if x not in ("--front", "--back")]
    if not flags and opt.get("role", "").strip().casefold() == "slack":
        flags = ["--front"]                      # the role slack is a front agent on the surface slack: the side need not be said
    sender = (opt.get("sender") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "").strip()
    if len(a) != 2 or len(flags) != 1 or not opt.get("role", "").strip() or not opt.get("mandate", "").strip():
        print(PROJECT_AGENT_USAGE); return 1
    if not sender: print("no asking session: pass --sender <transcript id | cse_ id>, or run it where $CLAUDE_CODE_SESSION_ID is set (a name is not accepted)"); return 1
    status, d = post("project-agent", {"project": a[0], "name": a[1], "role": opt["role"], "front": flags[0] == "--front", "mandate": opt["mandate"], "sender": sender, **({"surface": opt["surface"]} if "surface" in opt else {})}, timeout)
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


AGENT_NAME_USAGE = "usage: client.py get agent-name <project> <name> [<name> ...]   (at most 20 names, none with a comma)"


def agent_name(argv: list[str], timeout: float = 20.0) -> int:
    """`get agent-name <project> <name>...`: ask whether each name is acceptable for a new agent of the project (the register's checks, nothing written) → the server's JSON on stdout, exit 0 whenever the
    call answers; 1 and the reason on stderr when refused (an unknown project), misused, or not reached."""
    a = [x.strip() for x in argv]
    if len(a) < 2 or not all(a) or any(x.startswith("--") for x in a) or any("," in x for x in a):
        print(AGENT_NAME_USAGE, file=sys.stderr); return 1
    status, body = get("agent-name", timeout=timeout, key=a[0], names=",".join(a[1:]))
    if status != 200: print(f"stackshot: agent name not checked [{status}] {body}"[:700], file=sys.stderr); return 1
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


PROJECT_AGENT_MANDATE_USAGE = 'usage: client.py post project-agent-mandate <project> <name> --mandate "<one line>" [--sender <session id>]'


def project_agent_mandate(argv: list[str]) -> int:
    """`post project-agent-mandate <project> <name> --mandate "…" [--sender ID]`: change the mandate line of a listed agent in the project record (the page follows) → the server's JSON on
    stdout, exit 0; 1 and the reason on stderr when refused, not reached or misused. The server allows the agent marked as the project's keeper and its front agents, told by the asking session's id: --sender,
    else $CLAUDE_CODE_SESSION_ID."""
    a, opt = list(argv), {}
    for k in ("mandate", "sender"):
        if "--" + k in a:
            i = a.index("--" + k)
            if i + 1 >= len(a): print(f"--{k} needs a value\n{PROJECT_AGENT_MANDATE_USAGE}", file=sys.stderr); return 1
            opt[k] = a[i + 1]; del a[i:i + 2]
    sender = (opt.get("sender") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "").strip()
    if len(a) != 2 or not all(x.strip() for x in a) or any(x.startswith("--") for x in a) or not opt.get("mandate", "").strip():
        print(PROJECT_AGENT_MANDATE_USAGE, file=sys.stderr); return 1
    if not sender: print("no asking session: pass --sender <transcript id | cse_ id>, or run it where $CLAUDE_CODE_SESSION_ID is set (a name is not accepted)", file=sys.stderr); return 1
    return _post_json("project-agent-mandate", {"project": a[0].strip(), "name": a[1].strip(), "mandate": opt["mandate"], "sender": sender}, "mandate not changed", 120.0)     # the page's gbrain read, write and read back


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


INBOX_HOLD_USAGE = "usage: client.py post inbox-hold <key> [<key> ...] [--kind msg|hub] [--minutes N]   (the keys: the session's transcript id and its name)"
INBOX_RELEASE_USAGE = "usage: client.py post inbox-release <key> [<key> ...] [--kind msg|hub]"


def _inbox_keys(argv: list[str], names: tuple[str, ...], usage: str) -> tuple[list[str], dict] | None:
    """Positional keys and `--name value` options of an inbox hold call → (keys, options); None (the usage on stderr) when a value is missing, a key is empty or none is given."""
    a, opt = list(argv), {}
    for k in names:
        if "--" + k in a:
            i = a.index("--" + k)
            if i + 1 >= len(a): print(f"--{k} needs a value\n{usage}", file=sys.stderr); return None
            opt[k] = a[i + 1]; del a[i:i + 2]
    if not a or any(not x.strip() or x.startswith("--") for x in a): print(usage, file=sys.stderr); return None
    return [x.strip() for x in a], opt


def inbox_hold(argv: list[str]) -> int:
    """`post inbox-hold <key>... [--kind K] [--minutes N]`: hold a session's inbox on the server → the server's JSON on stdout, exit 0; 1 and the reason on stderr when refused, misused or not reached."""
    got = _inbox_keys(argv, ("kind", "minutes"), INBOX_HOLD_USAGE)
    if got is None: return 1
    keys, opt = got
    body: dict = {"keys": keys}
    if opt.get("kind"): body["kinds"] = [opt["kind"]]
    if opt.get("minutes"): body["minutes"] = opt["minutes"]
    return _post_json("inbox-hold", body, "hold not made", 30.0)


def inbox_release(argv: list[str]) -> int:
    """`post inbox-release <key>... [--kind K]`: lift a hold on a session's inbox → the server's JSON on stdout, exit 0; 1 and the reason on stderr when refused, misused or not reached."""
    got = _inbox_keys(argv, ("kind",), INBOX_RELEASE_USAGE)
    if got is None: return 1
    keys, opt = got
    body: dict = {"keys": keys}
    if opt.get("kind"): body["kinds"] = [opt["kind"]]
    return _post_json("inbox-release", body, "hold not lifted", 30.0)


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


CATCH_USAGE = ('usage: client.py post catch - < catch.json     (one JSON object: hook, id, t, pane, kind, and sender, outcome, first)\n'
               '       client.py post catch --hook <name> --id <id> --t <ISO time with offset> --pane <session> --kind <kind> [--sender <raw sender>] [--outcome <text>] [--first <text>]')


def catch(argv: list[str], timeout: float = 20.0, text: str | None = None) -> int:
    """`post catch -` (the fields as one JSON object on stdin) or `post catch --hook H --id I --t T --pane P --kind K [--sender S] [--outcome O] [--first F]` (a flag wins over the JSON): a hook's catch of a turn that
    signed off with a no-ask phrase after a trigger-started turn, sent to the server's catch log -> exit 0 and "ok" or "duplicate" on stdout; 1 and the reason on stderr when refused, not reached or misused."""
    a = list(argv)
    from_stdin = "-" in a
    a = [x for x in a if x != "-"]
    opt = _opts(a, ("hook", "id", "t", "pane", "kind", "sender", "outcome", "first"), CATCH_USAGE)
    if opt is None: return 1
    body: dict = {}
    if from_stdin:
        try: body = json.loads(sys.stdin.read() if text is None else text)
        except ValueError: print("the JSON on stdin does not parse: send one object\n" + CATCH_USAGE, file=sys.stderr); return 1
        if not isinstance(body, dict): print("the JSON on stdin is not an object\n" + CATCH_USAGE, file=sys.stderr); return 1
    body.update(opt)
    if not all(isinstance(body.get(k), str) and body[k].strip() for k in ("hook", "id", "t", "pane", "kind")):
        print("hook, id, t, pane and kind are required, as text\n" + CATCH_USAGE, file=sys.stderr); return 1
    status, d = post("catch", body, timeout)
    if status != 200 or not isinstance(d, dict):
        print(f"stackshot: catch not recorded [{status}] {d.get('error') if isinstance(d, dict) else d}"[:1200], file=sys.stderr); return 1
    print("duplicate" if d.get("duplicate") else "ok"); return 0


ANCHOR_ADD_USAGE = ('usage: client.py post anchor-add - < anchors.json     (one JSON object: project, add (a list of 1 to 10 pull request or issue URLs), sender, and optionally items (a list of item ids))\n'
                    '       {"project": "projects/<slug>", "add": ["https://github.com/<owner>/<repo>/pull/<n>"], "items": ["<item id>"], "sender": "<the session or script>"}')


def anchor_add(argv: list[str], timeout: float = 20.0, text: str | None = None) -> int:
    """`post anchor-add -` (the fields as one JSON object on stdin): add anchors to a project, or to some of its open items, as the anchors tool's add does -> exit 0 and the server's text (the project's anchors
    as the tool lists them) on stdout; 1 and the reason on stderr when refused, not reached or misused. Only adds: this route takes no removal."""
    if argv != ["-"]: print(ANCHOR_ADD_USAGE, file=sys.stderr); return 1
    try: body = json.loads(sys.stdin.read() if text is None else text)
    except ValueError: print("the JSON on stdin does not parse: send one object\n" + ANCHOR_ADD_USAGE, file=sys.stderr); return 1
    if not isinstance(body, dict): print("the JSON on stdin is not an object\n" + ANCHOR_ADD_USAGE, file=sys.stderr); return 1
    add = body.get("add")
    if not all(isinstance(body.get(k), str) and body[k].strip() for k in ("project", "sender")) or not (isinstance(add, list) and add):
        print("project and sender are required, as text, and add as a non-empty list\n" + ANCHOR_ADD_USAGE, file=sys.stderr); return 1
    status, d = post("anchor-add", body, timeout)
    if status != 200 or not isinstance(d, dict):
        print(f"stackshot: anchors not added [{status}] {d.get('error') if isinstance(d, dict) else d}"[:1200], file=sys.stderr); return 1
    print(d.get("result") or "ok"); return 0


AGENT_STATE_USAGE = "usage: client.py post agent-state --file <path>     (the file is the snapshot's JSON body, at most 1,000,000 bytes)"
AGENT_STATE_MAX = 1_000_000     # the server's limit for the body (stackshot/service/agent_state.py MAX_BYTES): a larger file is refused here, before anything is sent


def _one_line(text: str, tok: str = "", limit: int = 900) -> str:
    """`text` as one line: the secret `tok` taken out, every control character (a newline in a path, an escape) and every run of blanks collapsed to one space, cut at `limit`."""
    return " ".join(re.sub(r"[\x00-\x1f\x7f-\x9f]+", " ", _scrub(str(text), tok)).split())[:limit]


def _secret() -> str:
    """What this process sends as its Bearer, for taking it out of a text: the pass when $STACKSHOT_CLIENT_PASS is set, else this machine's token ("" when there is none)."""
    pas = _pass()
    if pas: return pas
    try: return open(TOKEN, encoding="utf-8").read().strip()
    except Exception: return ""


def _post_file(what: str, noun: str, argv: list[str], usage: str, limit: int, timeout: float, stdin_ok: bool = False) -> int:
    """`post <what> --file <path>` for a verb whose whole body is one JSON file the caller wrote: the file's bytes go to `POST /client/<what>` exactly as they are, never parsed here. With `stdin_ok`, the path `-` is
    standard input (read the same way, to the same limit). Prints the server's answer as JSON and exits 0 (an answer `{"kept": "newer"}`, a list the server did not store, also puts the line `kept: the server holds a newer list` on stderr); 1 and one line on stderr for a file that is missing, unreadable, not a regular file (a folder, a pipe, a
    device) or over `limit` bytes (nothing is sent), a refusal (the server's reason), a server that is not reached ([0]) or a misuse (usage). A path or a server text in that line has control characters collapsed and
    this machine's token (or the pass in use) taken out."""
    opt = _opts(argv, ("file",), usage)
    if opt is None: return 1
    if not opt.get("file", "").strip(): print(usage, file=sys.stderr); return 1
    path, sec = opt["file"], _secret()
    from_stdin = stdin_ok and path == "-"
    def refuse(why: str) -> int: print(_one_line(f"stackshot: {noun} not sent: {'standard input' if from_stdin else path} {why}", sec), file=sys.stderr); return 1
    try:
        fd = 0 if from_stdin else os.open(path, os.O_RDONLY | os.O_NONBLOCK)      # non-blocking: a pipe with no writer opens at once instead of waiting for one
    except OSError as e: return refuse(f"is not readable ({type(e).__name__})")
    try:
        if not from_stdin and not stat.S_ISREG(os.fstat(fd).st_mode): return refuse("is not a regular file")
        chunks, left = [], limit + 1
        while left > 0:
            chunk = os.read(fd, min(left, 1 << 20))
            if not chunk: break
            chunks.append(chunk); left -= len(chunk)
        data = b"".join(chunks)
    except OSError as e: return refuse(f"is not readable ({type(e).__name__})")
    finally:
        if not from_stdin: os.close(fd)
    if len(data) > limit: return refuse(f"is over the {limit}-byte limit")
    status, d = post(what, {}, timeout, raw=data)
    if status != 200 or not isinstance(d, dict):
        err = d.get("error") if isinstance(d, dict) else None
        reason = _one_line(err, sec) if err else _one_line(d if isinstance(d, str) else json.dumps(d, ensure_ascii=False, default=str), sec, 200)      # no `error` key: the body's first 200 characters
        print(_one_line(f"stackshot: {noun} not sent [{status}] {reason}", sec), file=sys.stderr); return 1
    if d.get("kept") == "newer": print("kept: the server holds a newer list", file=sys.stderr)      # answered 200 but not stored: said once on stderr, exit 0 (the answer is still printed)
    print(json.dumps(d, ensure_ascii=False)); return 0      # (an answer of {"kept": "newer"} also said its line on stderr above)


def agent_state(argv: list[str], timeout: float = 60.0) -> int:
    """`post agent-state --file <path>`: the fleet's session manager pushes which registered agents are busy and which idle, the whole fleet in one JSON file that REPLACES the last snapshot
    (`POST /client/agent-state`). The file's bytes go to the server as they are, never parsed here. Prints the server's answer ({"ok": true, "agents": N}) and exits 0; 1 and one line on stderr
    for a file that is missing, unreadable, not a regular file (a folder, a pipe, a device) or over the limit (nothing is sent), a refusal (the server's reason), a server that is not reached ([0]) or a
    misuse (usage). A path or a server text in that line has control characters collapsed and this machine's token taken out."""
    return _post_file("agent-state", "agent state", argv, AGENT_STATE_USAGE, AGENT_STATE_MAX, timeout)


MACHINES_USAGE = ("usage: client.py post machines --file <path>     (the file is the machine list's JSON body, at most 1,000,000 bytes; `--file -` or a bare `-` reads standard input)\n"
                  '       {"schema": 1, "written": <epoch s>, "machines": [{"name", "hostname", "letter", "ssh", "addresses": [...], "roles": ["sala-host" | "stackshot-host"], "retired": false, "sources": [...], optional: "online": true|false|null, "last_seen": <epoch s>|null, "versions": {...}|null, "checked": <epoch s>|null}], "not_read": [...]}\n'
                  '       the answer, with a "dropped" list naming a reading the server left out of a machine, is printed on stdout only; nothing is said on stderr for it')
MACHINES_BODY_MAX = 1_000_000     # the server's limit for the body (stackshot/service/machines_list.py MAX_BYTES): a larger file is refused here, before anything is sent


def machines(argv: list[str], timeout: float = 60.0) -> int:
    """`post machines --file <path>` (or `--file -`, or a bare `-`, for standard input): the fleet manager posts its machine list (`POST /client/machines`), which the server keeps as the last good list. The file's
    bytes go to the server as they are, never parsed here. Prints the server's answer ({"ok": true, "machines": N}) and exits 0, with one line on stderr, `kept: the server holds a newer list`, when the answer is {"ok": true, "kept": "newer"} (the list was not stored); 1 and one line on stderr for a file that is missing, unreadable, not a regular
    file or over 1,000,000 bytes (nothing is sent), a refusal (the server's reason: 400 a body that does not fit, 413 a body over the limit), a server that is not reached ([0]) or a misuse (usage)."""
    return _post_file("machines", "machine list", ["--file", "-"] if argv == ["-"] else argv, MACHINES_USAGE, MACHINES_BODY_MAX, timeout, stdin_ok=True)


JOB_FAILED_USAGE = "usage: client.py job-failed <unit> <host> <ISO-Z time of the failing run, 2026-11-23T02:15:00Z> <project: a page key, a scope/project label, or - for none>"
JOB_OK_USAGE = "usage: client.py job-ok <unit> <host> <ISO-Z time of the successful run, 2026-11-23T02:15:00Z>"


def _job_alert(what: str, argv: list[str], keys: tuple[str, ...], usage: str, timeout: float) -> int:
    """`job-failed <unit> <host> <time> <project>` / `job-ok <unit> <host> <time>`: positional only (a project of `-` is a value, never an option) -> exit 0 (job-failed prints the item's id, job-ok the ids it
    closed, none when none was open), 1 and the reason on stderr when refused, not reached or misused."""
    if len(argv) != len(keys) or any(not a.strip() for a in argv): print(usage, file=sys.stderr); return 1
    status, d = post(what, dict(zip(keys, (a.strip() for a in argv))), timeout)
    if status != 200 or not isinstance(d, dict):
        print(f"stackshot: {what} not sent [{status}] {d.get('error') if isinstance(d, dict) else d}"[:1200], file=sys.stderr); return 1
    if what == "job-failed":
        if not d.get("item"): print("stackshot: job-failed not filed [200] the server answered no item id", file=sys.stderr); return 1
        if d.get("fallback"): print(f"stackshot: {d['item']} is with {d.get('mover')}: the job's project was not its own builder's", file=sys.stderr)
        print(d["item"]); return 0
    for gid in d.get("closed") or []: print(gid)
    if not d.get("closed") and "older" in str(d.get("note") or ""): print(f"stackshot: {d['note']}", file=sys.stderr)
    return 0


def job_failed(argv: list[str], timeout: float = 30.0) -> int:
    return _job_alert("job-failed", argv, ("unit", "host", "time", "project"), JOB_FAILED_USAGE, timeout)


def job_ok(argv: list[str], timeout: float = 30.0) -> int:
    return _job_alert("job-ok", argv, ("unit", "host", "time"), JOB_OK_USAGE, timeout)


ITEM_OPEN_USAGE = ('usage: client.py post item-open <kind>:<what> --project <key|id|slug> --subject "<action and object>" --mover <agent> --step "<agent>: <what it does>" '
                   '--line "<fact>" [--line "<fact>" ...] [--sender <label>]')


def item_open(argv: list[str], timeout: float = 60.0) -> int:
    """`post item-open <marker> --project P --subject S --mover M --step "M: ..." --line L [--line L ...] [--sender L]`: a script asks for one board item for a background agent of a project
    (one open item per marker; a repeat answers the same item) -> exit 0 and the item's id on stdout; 1 and the reason on stderr when refused, not reached or misused."""
    if not argv or argv[0].startswith("--"): print(ITEM_OPEN_USAGE, file=sys.stderr); return 1
    marker, a, opt, lines = argv[0].strip(), list(argv[1:]), {}, []
    for k in ("project", "subject", "mover", "step", "line", "sender"):
        while "--" + k in a:
            i = a.index("--" + k)
            if i + 1 >= len(a): print(f"--{k} needs a value\n{ITEM_OPEN_USAGE}", file=sys.stderr); return 1
            if k == "line": lines.append(a[i + 1])
            else: opt[k] = a[i + 1]
            del a[i:i + 2]
    if a or not marker or not all(opt.get(k, "").strip() for k in ("project", "subject", "mover", "step")) or not lines:
        print(ITEM_OPEN_USAGE, file=sys.stderr); return 1
    body = {"marker": marker, "project": opt["project"], "subject": opt["subject"], "mover": opt["mover"], "step": opt["step"], "description": lines}
    if opt.get("sender", "").strip(): body["sender"] = opt["sender"].strip()
    status, d = post("item-open", body, timeout)
    if status != 200 or not isinstance(d, dict) or not d.get("item"):
        print(f"stackshot: item not opened [{status}] {d.get('error') if isinstance(d, dict) else d}"[:1200], file=sys.stderr); return 1
    print(d["item"]); return 0


ITEM_SYNC_USAGE = ('usage: client.py post item-sync <kind>:<what> open --project <key|id|slug> --subject "<action and object>" --mover <the person> --then <agent> --step "<what the person does>" '
                   '--line "<fact>" [--line "<fact>" ...] [--sender <label>]\n'
                   '       client.py post item-sync <kind>:<what> refresh --line "<fact>" [--line "<fact>" ...] [--sender <label>]\n'
                   '       client.py post item-sync <kind>:<what> close [--reason "<why>"] [--sender <label>]')
ITEM_SYNC_OPTS = {"open": ("project", "subject", "mover", "then", "step", "line", "sender"), "refresh": ("line", "sender"), "close": ("reason", "sender")}


def item_sync(argv: list[str], timeout: float = 60.0) -> int:
    """`post item-sync <marker> open|refresh|close …`: a script keeps one board item for the person in step with a condition it checks (open while it holds, refreshed on every run that still finds it, closed when it is gone)
    -> exit 0 and one line on stdout ("<item> opened | refreshed | closed", or that no item was open); 1 and the reason on stderr when refused, not reached or misused."""
    if len(argv) < 2 or argv[0].startswith("--") or argv[1] not in ITEM_SYNC_OPTS: print(ITEM_SYNC_USAGE, file=sys.stderr); return 1
    marker, verb, a, opt, lines = argv[0].strip(), argv[1], list(argv[2:]), {}, []
    for k in ITEM_SYNC_OPTS[verb]:
        while "--" + k in a:
            i = a.index("--" + k)
            if i + 1 >= len(a): print(f"--{k} needs a value\n{ITEM_SYNC_USAGE}", file=sys.stderr); return 1
            if k == "line": lines.append(a[i + 1])
            else: opt[k] = a[i + 1]
            del a[i:i + 2]
    if a or not marker or (verb == "open" and not all(opt.get(k, "").strip() for k in ("project", "subject", "mover", "then", "step"))) or (verb != "close" and not lines):
        print(ITEM_SYNC_USAGE, file=sys.stderr); return 1
    body: dict = {"action": verb, "marker": marker}
    for k, v in opt.items():
        if v.strip(): body[k] = v
    if lines: body["description"] = lines
    status, d = post("item-sync", body, timeout)
    if status != 200 or not isinstance(d, dict) or not (d.get("item") or d.get("action") == "none"):
        print(f"stackshot: item not synced [{status}] {d.get('error') if isinstance(d, dict) else d}"[:1200], file=sys.stderr); return 1
    print(f"{d['item']} {d.get('note') or d.get('action')}" if d.get("item") else str(d.get("note") or f"no open item for {marker}; nothing was done")); return 0


PROJECT_ACTIVITY_USAGE = "usage: client.py project-activity [--json]"


def project_activity(argv: list[str], timeout: float = 20.0) -> int:
    """`project-activity [--json]`: per project the epoch of its newest anchor notice from outside and of its owner's newest input, as one line each
    ("<project key> <anchor|-> <owner|->") or, with --json, the server's {"projects": {key: {"anchor", "owner"}}} → exit 0 (nothing printed when no
    project has either time); 1 and the reason on stderr when the server is not reached or refuses (never an empty answer for a failure), 1 on misuse."""
    if any(a != "--json" for a in argv) or len(argv) > 1: print(PROJECT_ACTIVITY_USAGE, file=sys.stderr); return 1
    status, body = get("project-activity", timeout=timeout)
    try: rows = json.loads(body)["projects"] if status == 200 else None
    except Exception: rows = None
    if not isinstance(rows, dict): print(f"stackshot: project activity not read [{status}] {body}"[:600], file=sys.stderr); return 1
    if argv: print(json.dumps({"projects": rows}, ensure_ascii=False, sort_keys=True)); return 0
    for key in sorted(rows):
        r = rows[key] if isinstance(rows[key], dict) else {}
        print(key, *(r[k] if isinstance(r.get(k), int) and not isinstance(r.get(k), bool) else "-" for k in ("anchor", "owner")))
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
    if cmd == "project-activity":
        try: return project_activity(argv[2:])
        except Exception as e: print(f"stackshot: project activity not read ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr); return 1
    if cmd == "background-wanted":
        try:
            status, body = get("background-wanted", timeout=8.0)
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
    if cmd == "job-failed":
        try: return job_failed(argv[2:])
        except Exception as e: print(f"stackshot: job-failed not sent ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr); return 1
    if cmd == "job-ok":
        try: return job_ok(argv[2:])
        except Exception as e: print(f"stackshot: job-ok not sent ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr); return 1
    if cmd == "sweep-step-proof":
        try: return sweep_step_proof(argv[2:])
        except Exception as e: print(f"stackshot: sweep not run ({type(e).__name__}: {str(e)[:160]})"); return 1
    if cmd == "backfill-contact":
        try: return backfill_contact(argv[2:])
        except Exception as e: print(f"stackshot: backfill not run ({type(e).__name__}: {str(e)[:160]})"); return 1
    if cmd == "repoint":
        try: return repoint(argv[2:])
        except Exception as e: print(f"stackshot: items not moved ({type(e).__name__}: {str(e)[:160]})"); return 1
    if cmd == "sweep-released":
        try: return sweep_released(argv[2:])
        except Exception as e: print(f"stackshot: sweep not run ({type(e).__name__}: {str(e)[:160]})"); return 1
    if cmd == "post" and len(argv) > 2 and argv[2] == "project-agent":
        try: return project_agent(argv[3:])
        except Exception as e: print(f"stackshot: agent not listed ({type(e).__name__}: {str(e)[:160]})"); return 1
    for verb, fn, what in (("project", project_new, "project not made"), ("project-list", project_list, "project not listed"),
                          ("project-agent-mandate", project_agent_mandate, "mandate not changed"),
                          ("project-agent-rename", project_agent_rename, "agent not renamed"), ("project-agent-retire", project_agent_retire, "agent not retired"), ("for-you-seen", for_you_seen, "not marked seen"), ("watch", watch, "flag not set"),
                          ("inbox-hold", inbox_hold, "hold not made"), ("inbox-release", inbox_release, "hold not lifted")):
        if cmd == "post" and len(argv) > 2 and argv[2] == verb:
            try: return fn(argv[3:])
            except Exception as e: print(f"stackshot: {what} ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr); return 1
    if cmd == "get" and len(argv) > 2 and argv[2] == "projects":
        try: return projects(argv[3:])
        except Exception as e: print(f"stackshot: projects not read ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr); return 1
    if cmd == "get" and len(argv) > 2 and argv[2] == "agent-name":
        try: return agent_name(argv[3:])
        except Exception as e: print(f"stackshot: agent name not checked ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr); return 1
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
    if cmd == "post" and len(argv) > 2 and argv[2] == "catch":
        try: return catch(argv[3:])
        except Exception as e: print(f"stackshot: catch not sent ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr); return 1
    if cmd == "post" and len(argv) > 2 and argv[2] == "anchor-add":
        try: return anchor_add(argv[3:])
        except Exception as e: print(f"stackshot: anchors not added ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr); return 1
    if cmd == "post" and len(argv) > 2 and argv[2] == "agent-state":
        try: return agent_state(argv[3:])
        except Exception as e: print(f"stackshot: agent state not sent ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr); return 1
    if cmd == "post" and len(argv) > 2 and argv[2] == "machines":
        try: return machines(argv[3:])
        except Exception as e: print(f"stackshot: machine list not sent ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr); return 1
    if cmd == "post" and len(argv) > 2 and argv[2] == "item-open":
        try: return item_open(argv[3:])
        except Exception as e: print(f"stackshot: item not opened ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr); return 1
    if cmd == "post" and len(argv) > 2 and argv[2] == "item-sync":
        try: return item_sync(argv[3:])
        except Exception as e: print(f"stackshot: item not synced ({type(e).__name__}: {str(e)[:160]})", file=sys.stderr); return 1
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
        asks = "--question" in a
        a = [x for x in a if x != "--question"]
        for f in ("--sender", "--release", "--pr"):
            opt[f] = a.pop(a.index(f) + 1) if f in a and a.index(f) + 1 < len(a) else ""
            a = [x for x in a if x != f]
        sender = opt["--sender"]
        if len(a) != 2 or not sender or opt["--release"] not in ("", "green", "red") or (fyi and asks):
            print("usage: client.py message <to> <text | -> --sender <label> [--fyi | --question] [--release green|red --pr <PR url>]\n"
                  "  --fyi: the message asks nothing of its receiver (news, a result). A background agent or a front agent gets it with its next turn, not a turn of its own, "
                  "and a front agent needs no mark on the first line for it; a front agent whose hook cannot fetch held lines does not get it, and the call fails (exit 1); without --fyi a message to a front agent that is marked for the person and names an open item of his is delivered as a turn only while he talks with that agent, else written onto the item (held for its next turn when no item can take it) and starts no turn; any other goes to the project's background agent.\n"
                  "  --question: a front agent asks the session it writes to something; only a reply to a message sent with it is an answer. Not with --fyi, and not in the owner's own name."); return 1
        text = sys.stdin.read() if a[1] == "-" else a[1]
        status, body = message(a[0], text, sender, release=opt["--release"], pr=opt["--pr"], fyi=fyi, question=asks)
        print(body if status == 200 else f"[{status}] {body}"); return 0 if status == 200 else 1
    if cmd == "mint" and len(argv) > 2:
        try: path = mint(argv[2])
        except ValueError as e: print(e); return 1
        print(f"minted a token for {argv[2]} → {path} (0600; not shown). The server knows it at once."); return 0
    if cmd == "keys":
        from stackshot.fleet import caller_keys as _keys
        verb = argv[2] if len(argv) > 2 else ""
        try:
            if verb == "list" and len(argv) == 3:
                rows = _keys.listing()
                print("\n".join(rows) if rows else "no key is enrolled"); return 0
            if verb == "approve" and len(argv) == 4:
                fp, e = _keys.approve(argv[3])
                print(f"approved {_keys.short(fp)}  {e['sender']}  {e['label']}" if fp else "no one pending key starts with that (at least 8 hex characters; `keys list` shows them)"); return 0 if fp else 1
            if verb == "revoke" and len(argv) == 4:
                fp, kind = _keys.revoke(argv[3])
                print(f"revoked {_keys.short(fp)} ({kind})" if fp else "no one key starts with that (at least 8 hex characters; `keys list` shows them)"); return 0 if fp else 1
        except _keys.KeysFileError as e:
            print(str(e), file=sys.stderr); return 1
        print("usage: client.py keys list | approve <fingerprint> | revoke <fingerprint>", file=sys.stderr); return 1
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
