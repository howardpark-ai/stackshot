## description autonomy
How far a session may go alone on a kind of action, for a person: the person's row of the autonomy profile. One kind
returns `<kind>: <level>`; no kind returns every kind, one line each, `<kind>: <level> · <what the kind covers>`. A
level is one of auto (act without asking), when-told (act when the person's words, or a relayed call carrying
them, say so), ask-first (propose it as a board step with options and a recommendation, and wait for the pick) and
hand-on (do not act and do not ask: pass it to the person who must take it, as that person's step). A missing person,
kind or level, an unknown kind and an unreadable profile all read hand-on. Read only; nothing here changes the
profile.

## param person
A member's name or alias, as in the members list: the person the session acts for, else the item's member, else the
board's owner.

## param kind
One kind of action (release, release-migrating, design-choice, new-notice, spend, message-person, email,
connector-write, merge, delete, retire, revive, fleet-op, public-repo); empty = every kind of the person.
