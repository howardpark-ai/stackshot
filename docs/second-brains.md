# Second brains

What this page covers: projects whose pages live in a second notes brain: routing of new pages, reads and writes, failing open, secrets and thin clients. Back to the [README](../README.md).

Some projects' pages can live in a second notes brain. The instance reaches it the same two ways as the first: a separate local git copy
(kept in sync by another process; stackshot only reads it) and the gbrain CLI with its own home folder and sign-in. Each `[[brains]]` entry
in `stackshot.toml` names one (`stackshot.example.toml` documents the keys). `stackshot/projects/brains.py` resolves a page key to its brain: the first entry
whose `slugs` list the key (or a page above it) or whose `prefixes` it starts with; every other key is in the default brain, `paths.brain`.

**Where a new page starts.** `slugs` and `prefixes` name pages that already live in a second brain, so a page created later under a similar
name would start in the default brain. Two optional keys on an entry say where an absent page starts:

- `new_prefixes = ["projects/beta-"]`: plain prefixes of a page key (end each in `-` or `/`). A key that starts with one, matches no `slugs`
  or `prefixes` entry, and exists in no brain's local copy (neither the page nor a page it is a sub-page of) is routed to this entry's brain,
  so the page is created there and every later read and write on the server box finds it there. The first entry whose `new_prefixes` match wins.
  Routing of a new page depends on the local copies being present and current: a page created in the database but not yet in the copy is
  treated as absent, and when the default brain's copy is unusable (missing, no `.git`, no page in it) every page stays with the default brain.
  A client box gets only `slugs` and `prefixes` (it has no copy to tell an existing page from a new one), so it links a page created by
  `new_prefixes` to the default mirror unless its slug is in `slugs`.
- `keep = ["beta-old"]`: fragments; a page key that contains one of them stays in the default brain, even when a `new_prefixes` entry
  matches. `keep` wins over `new_prefixes` and has no effect without it.

A page that already exists is routed exactly as before: `new_prefixes` never moves a page, so a page of the default brain that matches a
prefix stays where it is. A bad value (not a list of strings, an empty or non-string item, a `new_prefixes` entry without a `/` or not
ending in `-` or `/`) is named by `config.notes` at the start and on a reload and is ignored.

## A shared brain

A brain whose pages other people also read and write is marked `shared = true` on its `[[brains]]` entry (`[gbrain] shared = true` for the default brain). stackshot then writes nothing of
its board onto a page of that brain: every page-store write for one of its slugs (a Current-state edit by the audit's page call, a timeline line such as the router's note or an archive's,
a new page, the copy of a project's lines) is refused with a line that names the mark (`brains.shared_refusal`; `page_debt.BrainIO` makes the refusal for every writer, before the gbrain CLI
is called), and a page of it owes no page update to a session (pages owed charges nothing there, and drops a debt charged before the mark was set). Reads are unchanged, and a project
verb still writes the project record: its answer says `mirror.state` = `retired` and gives the reason. A project verb that moves a page (`move-page`, which runs `rename_page.py`) is refused with 403 when the old or the new key is in a shared brain, before any step runs,
a dry run included; the router's timeline note on such a page is skipped (no `note_error`, the ruling is unchanged). `rename_page.py` run by hand and `page_keeper.py` (the one-time pass that renames a
page's `session:` line) are an operator's tools, not board writes, and are not refused. Only a boolean `true` marks a brain; `config.notes` names any other value, and the page-store check itself
never blocks a write because the brain list could not be read. A brain is marked by its `slugs`, `prefixes` and `new_prefixes` only: a shared subset inside the same gbrain home as the default
brain (a source id, not a separate home) cannot be marked yet.

### The copy of the record onto pages, and the read-through

stackshot used to copy a project's record onto its page after every project verb: the `display-name:`, `status:` and `agents:` lines (`project_verbs.mirror`). Its own readers read the record
first (`project_registry.apply`), so the copy only served scripts that read the lines. It is retired in two steps. Per brain, the shared mark above: such a page never gets the copy. For every
brain at once, one switch: `[pages] copy_project_lines = false`; a verb's `mirror.state` is then `retired` everywhere, and the page's three lines stay as they last were. The switch also stops the
creation of a page for a new project (`create --make-page` writes the record and no page); the page is made by hand or by the project's people. Nothing a reader needs is lost
meanwhile: `stackshot projects fields <id | page key | bare slug>` (`projects.fields`, run on the server box) prints a project's `display_name`, `status`, `agents` (front or background, role, mandate line),
`main` and `owner_key` as JSON, taking each field from the project's entry in the record and, for a field the entry does not hold or a project the record does not cover yet, from the page's own
lines; `source` and `from` say which. `projects fields --all` lists every page that names a project or lists an agent. A script reads this, never the lines. Exit 0 found, 1 no such project, 2 the
registry or the project record cannot be read on this machine (a damaged record is told, never answered from the pages' lines). Until the record covers a project (the migration), its page lines are the answer for it. A verb on such a project first makes its entry from the lines, so once the
copy is off the lines of a project stop following it from that verb on: turn the switch off only when nothing outside stackshot reads the lines any more.

- **Reads** use that brain's copy: the page registry (`stackshot/projects/pages.py registry` reads each brain's copy for the keys that brain holds), create's
  page check, the page hook's freshness and Current-state checks, pages owed, the audit's page call's shadow read, the search index, and the
  page links (the brain's `mirror_url`, else the file in its copy).
- **Writes** run the gbrain CLI with `GBRAIN_HOME=<home>` of the slug's brain (`rename_page.gb` reads the slug from the call), whatever
  `[pages] flavor` says for the default brain: a second brain is written through gbrain only.
- **Fail open.** A second brain whose copy is missing, is no usable copy (no `.git`, or no page in any page folder: an unmounted folder, a
  clone still being checked out) or is not synced for `stale_hours`, or whose CLI call fails, never blocks the board: create's page check and
  the page hook accept the item and log a warning naming the brain; pages owed and the audit's page call skip that brain's pages for the run
  (their debts are kept, not settled or charged); the registry keeps that brain's pages as it last read them (a stale copy is still read,
  with a warning). The default brain keeps its checks exactly as before.
- **One warning per outage, where a process lives long.** The server says each of these once until the brain reads again. The page hook
  starts a new process for every prompt, so it has no memory of the last one and repeats its line (on stderr, and in the prompt's nag line)
  at each prompt while the outage lasts.
- **The audit's page call retries.** When the CLI read of a second-brain page fails, that page gets no mark for the run, so the next audit run's pass tries again; the log keeps one line per outage.
- **A brain with no `home` is not reached through the CLI.** The gbrain CLI would run with the default home: a read would return the default
  brain's page for that slug and a write would put the page into the default brain. So a CLI call for that brain's slugs (a read, a put, a
  timeline line, a rename) is refused with a line saying so, and `config.notes` names the entry. A refused read is a page that could not be
  read: the audit's page call skips it and says so once per outage, naming the brain.
- **A remote brain's client secret: `secret_file`.** A remote brain's CLI also needs its OAuth client secret (it fails with "No client_secret
  available" on `GBRAIN_HOME` alone). An entry may name `secret_file`, a path (`~` allowed) to a JSON file with a `client_secret` key, or a plain
  file whose first line is the secret. The server reads it at each CLI call for that brain and sets `GBRAIN_REMOTE_CLIENT_SECRET` in that
  child's environment only: never in its own environment, a log, a note, an error message (an exact copy of the value in a CLI's output is removed) or the client
  config (`/client` serves the brain's name, mirror and slug rules, never this key). Keep the file mode 600: one that group or others can
  read (mode & 0o077) is not used, and `config.notes` (doctor, the start) says so, naming the path. A secret the server never takes from its own
  environment: the variable is removed from every child first and set only from the brain's file. A file that cannot be read, is empty, has
  no `client_secret`, or holds an unusable one (shorter than 16 characters, or with a control character) refuses the CLI calls for that brain with a line naming the path and the reason, said once per outage; the board carries
  on as with any other outage of that brain.
- **A brain that is a thin client of a remote gbrain.** Such a brain's CLI refuses `gbrain call <tool>` (error code `requires_local_engine`, "not
  routable") and forwards the named commands. A page read and a timeline line first run as `call get_page` and `call add_timeline_entry`; when
  the CLI answers with that refusal, the same read runs as `gbrain get <slug> --include-content --content-only --json` and the line as
  `gbrain timeline-add <slug> <date> <summary> [--detail …] [--source …] [--request-id …]` (a page write is `gbrain put`, which is forwarded
  as it is), and the brain is remembered for the life of the process so its later calls skip the refused form. No key is needed. A read that
  fails is never told as "no page": a project's page mirror (`mirror`), `adopt` and the audit's registry check name the CLI's own error
  (`mirror.state` = `failed`, a 502 for `adopt`), and only the brain's own `page_not_found` error reads as a page that is not there (an HTTP 404 or any other "not found" text is a failed read).
- **Prefixes end in `-` or `/`.** A prefix such as `projects/beta` also takes `projects/betamax`; `config.notes` warns about one that does not
  end in a separator, and about a repeated brain name.
- **Client boxes.** `stackshot client install --url` copies each brain's name, mirror link and slug rules into the client's config (marked
  `remote = true`: no copy and no home on that box), so its page links go to the right mirror. A stub left by a page rename links to the new
  page's own brain mirror, and says so when that brain has none.
- With no `[[brains]]` nothing changes: every page is read from `paths.brain` and written with the CLI's default home.
