## description invite
Let a person into this board by their Google address, or take that back. Admins only: the server checks who is
signed in. Registering returns a setup link and a ready invite mail (subject and body). The board sends no mail:
create the mail as a draft with your own mail connector, to that address, and do not send it, because it goes only
when the admin sends it; with no mail connector, show the admin the text to copy. The link holds no secret. The
registration makes the address a member, who reads and writes as any member does; a newcomer gets in only once
registered, with an address Google reports as verified, and the first sign-in binds the Google account, which every
later one has to be. Calling it again for a registered address returns the same link and mail. remove=true takes the
registration back: unless another entry still lets the address in, the connector refuses the person every list,
read and call from the next request on, sign-ins already issued included. A machine token or an enrolled key is
revoked separately.

## param address
The person's Google sign-in address, one address, such as name@example.com.

## param remove
true takes the registration back; the default registers the address.

## text FIRST_USE lead
A person who has just joined this board (they ask to get started, to be shown around, or say they were invited):
call brief, tell them in plain words what the board holds, which items wait on them and how to ask you to record
or move one, then do the first thing they ask for; create no item, page or project they did not ask for. An admin
lets a person in, or takes that back, with the invite tool.
