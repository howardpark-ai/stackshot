# Configuration: keywords for another language

What this page covers: the `keywords.*` keys that let an instance in another language list its own words, and how a words list is read. Back to the [README](../README.md).

The keys are grouped in three pages by what they set: [Configuration](configuration.md), [Configuration: project agents, runners, anchor-hub, router, auth and client](configuration-integrations.md) and [Configuration: keywords for another language](configuration-keywords.md). Each has the same four columns.

| Key | Example | Meaning | Set |
|---|---|---|---|
| `keywords.step_commands.shell_names` | `[]` | A list of words: other-language names of a shell (the English ones are PowerShell, pwsh, WSL, terminal, shell, console): a text that names one asks the owner to run something there. Added to the English words; empty adds nothing. Live. | |
| `keywords.step_commands.windows_words` | `[]` | A list of words: other-language names of Windows or PowerShell: a command with one of them says where it runs. Added to the English words; empty adds nothing. Live. | |
| `keywords.step_commands.run_commands` | `[]` | A list of words: other-language imperative phrases that ask the owner to run, type or paste something (run it, type it, paste it). Added to the English words; empty adds nothing. Live. | |
| `keywords.step_commands.after_command` | `[]` | A list of words: words that right after a command's closing backtick make it a command for the owner to run (the verb that follows its object; a particle may be part of the phrase). Added to the English words; empty adds nothing. Live. | |
| `keywords.step_commands.subject_markers` | `[]` | A list of words: the particles that mark a subject right before a backticked command: a session named as the subject runs it, not the owner. Added to the English words; empty adds nothing. Live. | |
| `keywords.step_commands.pointer_patterns` | `[]` | A list of patterns: other-language regular expressions for a step that points elsewhere ("see the description", "see below"). Added to the English words; empty adds nothing. Live. | |
| `keywords.step_commands.pane_cues` | `[]` | A list of words: other-language run cues that may stand before a pane-form `! command` (the English ones are type, run, enter, execute, paste). Added to the English words; empty adds nothing. Live. | |
| `keywords.router.decision` | `[]` | A list of words: other-language words for a decision: a notice with one needs the owner (weak signal). Added to the English words; empty adds nothing. Live. | |
| `keywords.router.urgent` | `[]` | A list of words: other-language words for urgent: a notice with one passes the quiet hours. Added to the English words; empty adds nothing. Live. | |
| `keywords.model_guards.wait_words` | `[]` | A list of words: other-language words that say an item waits (waiting, wait for): a next line with one reads as a wait. Added to the English words; empty adds nothing. Live. | |
| `keywords.model_guards.overnight_words` | `[]` | A list of words: other-language words for overnight: a doing item whose next line says so reads as a wait. Added to the English words; empty adds nothing. Live. | |
| `keywords.model_guards.defer_after_id` | `[]` | A list of words: other-language phrases that follow a board id and defer on it (closes, is done, after, until, before). Added to the English words; empty adds nothing. Live. | |
| `keywords.dates.month_suffix` | `[]` | A list of words: the word written right after a month number in a month-and-day date ("<month number> <this word> <day number> <day_suffix word>"). Added to the English words; empty adds nothing. Live. | |
| `keywords.dates.day_suffix` | `[]` | A list of words: the word written right after a day-of-month number (and after a number of days). Added to the English words; empty adds nothing. Live. | |
| `keywords.dates.week_suffix` | `[]` | A list of words: the word written right after a number of weeks. Added to the English words; empty adds nothing. Live. | |
| `keywords.dates.later_words` | `[]` | A list of words: the words after a number of days or weeks that mean "from now". Added to the English words; empty adds nothing. Live. | |
| `keywords.dates.tomorrow` | `[]` | A list of words: other-language words for tomorrow. Added to the English words; empty adds nothing. Live. | |
| `keywords.dates.day_after_tomorrow` | `[]` | A list of words: other-language words for the day after tomorrow. Added to the English words; empty adds nothing. Live. | |
| `keywords.dates.next_week` | `[]` | A list of words: other-language words for next week. Added to the English words; empty adds nothing. Live. | |
| `keywords.dates.next_month` | `[]` | A list of words: other-language words for next month. Added to the English words; empty adds nothing. Live. | |
| `keywords.pages.board_label` | `[]` | A list of words: other-language words for the Board label of a turn's closing board line. Added to the English words; empty adds nothing. Live. | |
| `keywords.pages.no_change` | `[]` | A list of words: other-language words for 'no change' in that line. Added to the English words; empty adds nothing. Live. | |
| `keywords.rebullet.pronouns` | `[]` | A list of words: other-language pronouns a rewrite must not resolve into a name (matched as whole words). Added to the English words; empty adds nothing. Live. | |
| `keywords.rebullet.negations` | `[]` | A list of words: other-language negation words or endings a rewrite must not lose (matched anywhere in a word). Added to the English words; empty adds nothing. Live. | |
| `keywords.rebullet.negation_words` | `[]` | A list of words: other-language negation words matched only as whole words. Added to the English words; empty adds nothing. Live. | |
| `keywords.reports.ask_words` | `[]` | A list of words: other-language words that make a report an ask (needs, please review, decide, approve). Added to the English words; empty adds nothing. Live. | |
| `keywords.draft.stems` | `[]` | A list of words: other-language words that say a step posts, sends or pastes a text (matched anywhere in the step). Added to the English words; empty adds nothing. Live. | |
| `keywords.draft.stem_patterns` | `[]` | A list of patterns: regular expressions for such words that need a condition after them (found anywhere in the step). Added to the English words; empty adds nothing. Live. | |
| `keywords.draft.standalone_stems` | `[]` | A list of words: such words that count only as a whole word, with at most one particle after them. Added to the English words; empty adds nothing. Live. | |
| `keywords.draft.particles` | `[]` | A list of words: the particles that may follow a standalone stem. Added to the English words; empty adds nothing. Live. | |
| `keywords.draft.ignore_phrases` | `[]` | A list of words: phrases that contain a stem but are not about posting a text (a screen share). Added to the English words; empty adds nothing. Live. | |
| `keywords.waiting.park_words` | `[]` | A list of words: other-language words for park, postpone or hold: the owner's answer with one parks the item. Added to the English words; empty adds nothing. Live. | |
| `keywords.server.command_cues` | `[]` | A list of words: other-language words that say an item waits on the owner running or pasting a command. Added to the English words; empty adds nothing. Live. | |
| `keywords.ask_options.particles` | `[]` | A list of words: the suffixes that may follow the last word of an option's label in a Recommend sentence (a language that glues them on): the label still counts as named. Added to the English words; empty adds nothing. Live. | |
| `keywords.ask_options.refusals_after` | `[]` | A list of words: other-language words that say 'not this option' right after a label (a language that puts the refusing word after it): the option right before one is turned away; an optional `particles` suffix and spaces may sit between, and the word needs no word boundary after it. There are no English words of this kind; empty adds nothing. Live. | |
| `keywords.ask_options.yes_no_words` | `[]` | A list of words: other-language words for yes, no, approve, decline, go and hold (the English ones are yes, no, yep, yeah, nope, ok, okay, agree, approve, accept, decline, reject, no-go, go ahead, go for it, go with it, hold off, hold on, and go or hold only as the whole stance). A needs=decision item with no options is accepted only when its Recommend part opens with one of them, since the page draws Yes / No under such an item; a `keywords.ask_options.particles` suffix may follow one. Added to the English words; empty adds nothing. Live. | |
| `keywords.ask_options.refusals` | `[]` | A list of words: other-language words or phrases that say 'not this option' right before a label, letter or place (the English ones are not, no, avoid, never, skip, except, don't, instead of, rather than): the option after one is turned away. Added to the English words; empty adds nothing. Live. | |

The `keywords.*` rows are the words of another language. The matchers that read free text (a step, a notice, an owner's answer, a report) ship with English words only; an instance
that writes in another language lists its own words under `[keywords.<feature>]`, and each list ADDS to the English ones. A missing section or key is an empty list, which is the English
behavior exactly. A `words` list holds literal words or phrases (a space inside a phrase stands for any run of white space); a `patterns` list holds regular expressions. They are read
where they are used, so a reload takes a change at once, and `bin/stackshot doctor` names a section or key this version does not read, a value that is not a list of strings and a pattern that does not compile. The `[keywords.*]` tables are optional, and their values (the words of the operator's own language) live in the operator's private config, never in this public tree.
