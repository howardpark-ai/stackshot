# Answer a decision

An item that waits for a person's decision shows its question with one card per option. The person picks one, may add a note and sends; the answer is stored on the item, the question leaves their queue, and the session reads the answer.

## Sub-features

- `answer.ask`: the home page lists the item; its page offers the options to a signed-in viewer only.
- `answer.refuse`: an answer that is signed out, from another origin or with a wrong token is refused with 403 and records nothing.
- `answer.send`: a good answer redirects to the item with the notice code `sent=decision`.
- `answer.after`: the page shows the notice and offers no option; `get` returns the choice and the note.

## How to get to it (user POV)

- The home page `/`, in the person's own list.
- The item page `/items/<id>`, whose answer form posts to `/items/<id>/answer`.

## Driving it with verify_app_check

Preconditions: the baseline. Command: `tests/run-suite verify_app_check answer`.

- Ask: `create` with `needs=["decision"]`, an `ask` line, two `options` and `then="sparrow"`; `/` shows the subject; `form.ianswer` on the item page has both choices, and none when signed out.
- Refused answers: `app.post_form` with `signed=False`, with another `origin`, and with a changed `token` each return 403; `app.item(id)` has no `answers`.
- Send: `app.post_form` with the form's own hidden fields, `choice`, `text` and `act` returns 303 to `/items/<id>?sent=decision`.
- After: the stored record holds one answer with that choice and note, and `decision` is no longer in `needs`; the page shows `Sent: your answer is on the item`; `get` shows the choice and the note.

## Gotchas

- A decision item is the person's move: leave `mover` out and name the session that follows in `then`.
- No session runs in this instance, so nobody is told of the answer, whatever the page's notice says. The notice is not evidence of delivery.
- The form is sent as a plain POST. What the page's script does with the cards and the Send button needs a browser check (`tests/answer_back_check.py`, `tests/decision_pick_check.py`).
