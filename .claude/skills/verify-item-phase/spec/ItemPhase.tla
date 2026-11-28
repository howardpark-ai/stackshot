---- MODULE ItemPhase ----
\* A closed item stores no `phase` and no `waits_on`.
\* What a save stores comes from StampTable.tla, which extract_stamp.py reads off the real
\* stackshot/service/stamp.py `_phase_stamp`; nothing about a save is written by hand here.
EXTENDS StampTable

VARIABLES status,   \* "open" | "closed"                         (item["status"])
          shown,    \* what the item's fields read as            (model.view): "alive" | "wtime" | "wrelay"
          phase,    \* metadata.phase    as stored, "" = absent
          waitsOn   \* metadata.waits_on as stored, "" = absent

vars == <<status, shown, phase, waitsOn>>

\* the pair stored after a save is the one the code's stamp gave
Stores(r) == phase' = r[1] /\ waitsOn' = r[2]

Shown == {"alive", "wtime", "wrelay"}
Pairs == {<<"", "">>, <<"alive", "">>, <<"waiting", "time">>, <<"waiting", "relay">>}

\* any item as it may stand before this run: open, with any pair a save could have left
Init == /\ status = "open"
        /\ shown \in Shown
        /\ \E p \in Pairs : phase = p[1] /\ waitsOn = p[2]

\* a save that changes what the fields read as (an edit, a wait set or cleared), or none (a description edit)
Save == /\ \E s \in Shown :
            /\ shown' = s
            /\ Stores(Stamp[<<status, phase, waitsOn, s>>])
        /\ status' = status

\* the save that closes the item
Close == /\ status = "open"
         /\ status' = "closed"
         /\ Stores(Stamp[<<"closed", phase, waitsOn, shown>>])
         /\ shown' = shown

\* the save that reopens it
Reopen == /\ status = "closed"
          /\ status' = "open"
          /\ \E s \in Shown :
               /\ shown' = s
               /\ Stores(Stamp[<<"open", phase, waitsOn, s>>])

\* the clock moves what an open item's fields read as with no save (the phase sweep restamps it later)
Clock == /\ status = "open"
         /\ \E s \in Shown : shown' = s
         /\ UNCHANGED <<status, phase, waitsOn>>

Next == Save \/ Close \/ Reopen \/ Clock

Spec == Init /\ [][Next]_vars

ClosedStoresNone == status = "closed" => phase = "" /\ waitsOn = ""
====
