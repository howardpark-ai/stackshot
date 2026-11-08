# Second brains

What this page covers: projects whose pages live in a second notes brain: routing of new pages, reads and writes, failing open, secrets and thin clients. Back to the [README](../README.md).

Some projects' pages can live in a second notes brain. The instance reaches it the same two ways as the first: a separate local git copy
(kept in sync by another process; stackshot only reads it) and the gbrain CLI with its own home folder and sign-in. Each `[[brains]]` entry
in `stackshot.toml` names one (`stackshot.example.toml` documents the keys). `brains.py` resolves a page key to its brain: the first entry
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

- **Reads** use that brain's copy: the page registry (`pages.py registry` reads each brain's copy for the keys that brain holds), create's
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
