# The answer frame

What this page covers: one item's answer block that another site of yours shows in a frame: how to turn it on, the address, what each caller sees, the messages between the frame and the page that holds it, how an answer is sent, and what protects it. Back to the [README](../README.md).

The code is `stackshot/web/routes/answer_frame.py` (who asks, the headers) and `stackshot/web/ui/answer_frame.py` (the page, its states and its script). The tests are `tests/answer_frame_scenario.py` (the routes) and `tests/answer_frame_check.py` (a browser; CI runs it).

## Turning it on

```toml
[ui]
answer_frame_origins = ["https://chat.example.com"]
```

- The list is empty by default. While it is empty the address is answered like one no route has, and no response of the board says anything new about frames.
- Each entry is exactly `https://<host>` or `https://<host>:<port>`: no path, query, trailing slash, wildcard, space, semicolon, comma or quote, no user name, and a name in ASCII (a name in another script in its `xn--` form). A bad entry is a config note (`stackshot doctor`, the server's start) and is ignored: it never reaches a header. The key is read live.
- The board has to ask for a sign-in itself (`[auth] ui_open = false`, with auth on). A board served open, or with auth off, issues no board session, so the frame only ever shows its sign-in link.
- The page that holds the frame has to be on the same site as the board, over https (for example `chat.example.com` beside `board.example.com`). The sign-in cookie is `SameSite=Lax`, which a browser does not send into a frame under another site's page: there the frame always reads as signed out.

## The address

`GET /items/<key>/answer-frame?lang=<code>&theme=dark|light`

- `<key>` is the item as its page's own address takes it.
- `lang` is a language the board can draw (`en`, and the one in `[ui] locale_dir`). Without it, or with another value, the frame is in the signed-in person's board language; signed out, English.
- `theme` sets the colors. Without it, or with another value, the frame follows the device.

The page is the answer block alone, as the home page's Your move draws it: the question, the item's draft if it has one, the option cards, the note box and Send. It draws no title and no link to the item; the page that holds it knows both. It is as tall as its content and fits a width of 390 px without scrolling.

## What it shows

| State | When | What is on the page |
|---|---|---|
| `open` | The item is on the signed-in person's move and has options to pick (stored ones, or Yes and No). Also after a send that did not go through. | The question and the form. After a failed send, a line that says nothing was sent and why. |
| `sending` | A send is under way. | The form, locked. |
| `answered` | The question was answered, here or on the board. | The recorded answer: the question, who answered and when, the card and the note. Nothing can be pressed. |
| `changed` | The question is not the one this frame drew. | One line and a link to the item. Loading the frame again shows the new question. |
| `closed` | The item is not on the person's move, has nothing to pick, or does not exist. | One line and a link to the item. |
| `signed_out` | The request carries no board session. | A link that opens the item on the board in a new tab, and nothing of the item. An item that does not exist gives the same page. |

`changed` is a reading against the question first drawn, so only a frame that is already showing reaches it. A first load shows the question as it stands.

## Messages to the page that holds it

The frame posts this to `window.parent`, on load and whenever a field changes:

```json
{"source": "stackshot", "kind": "answer-frame", "v": 1, "item": "<key>", "height": 420, "state": "open", "typing": false}
```

- `height` is the content's height in CSS pixels. Give the frame that height and nothing scrolls inside it.
- `state` is one of the states above.
- `typing` is true while the note box has the focus.
- No message holds a word of the item, the answer, or a token.
- The target origin is always one of the configured origins, never `*`. A configured origin that is not the parent's receives nothing.

## Messages from the page that holds it

Both are taken only when the sender is the parent window and its origin is a configured one. `source` is any string.

| Message | What the frame does |
|---|---|
| `{"source": "...", "kind": "answer-frame", "v": 1, "do": "refresh"}` | Reads the item again. A pick and a typed note stay when the question is unchanged. |
| `{"source": "...", "kind": "answer-frame", "v": 1, "do": "theme", "theme": "dark"}` | Switches the colors (`dark` or `light`). |

A frame that shows `signed_out` also reads again by itself when it comes back into view, so a sign-in made in the new tab shows without the parent doing anything.

## Two frames of one item

Frames of the same item on one page share the pick, the note, a send under way and how it ended, over a `BroadcastChannel` on the board's own origin. The parent does nothing for it.

## Sending an answer

Send posts the form to the board's one answer route, `POST /items/<key>/answer`, with every check that route makes: a board session, the board's own origin, the token of this person and this item, and the reference of the question the form showed (a pick on a question rewritten since is not recorded). The answer is recorded under the signed-in member, as from the item's page. A request whose `Accept` header is exactly `application/json` gets `{"sent": "<code>"}` in place of the redirect, with the same codes the item page's notices read; nothing else about the route differs. A session's or a machine's token is not a board session and cannot answer here.

## What protects it

- Only this route's responses say who else may show them: `Content-Security-Policy: frame-ancestors 'self' <the configured origins>` and no `X-Frame-Options`, with `Cache-Control: no-store` and `X-Content-Type-Options: nosniff`. Every other response keeps what `stackshot/web/frame_guard.py` gives it. `frame-ancestors` is checked against every page above the frame, so a configured origin that is itself framed by another site shows nothing.
- A GET writes nothing to the board's data. Loading the frame counts as a visit for the length of the sign-in, as opening any board page does.
- What an item says is escaped, and the page's script reads its data from escaped attributes, never from text written into the script.
- Clicks. A page that may frame the board could try to place something over the frame, or move it, so that a person presses what they did not mean to. Answering takes two presses at two places (a card, then Send), nothing is picked beforehand, Send stays off until there is a pick or a note, and the parent can only ask for a refresh or a theme. It cannot read the frame, pick, type or send. These lower the risk and do not remove it: list only origins you run and trust as you trust the board.

## Known limit: an installed web app

A site installed to a phone's home screen may keep its cookies apart from the browser's, depending on the platform and its version. Where it does, a sign-in made in the page the link opens does not reach the frame, which stays signed out inside the installed app. Check this on the devices you use before relying on the frame there.
