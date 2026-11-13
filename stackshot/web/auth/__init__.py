"""auth: how a person or a client gets in to the server.

auth/signin.py is the board's own sign-in (the signed cookies, the guard a page asks, the board's own OAuth client and the /ui/login, /ui/callback and /ui/logout routes),
auth/oauth.py is the sign-in provider the MCP server is built with (and `_who`, the signed-in identity a tool asks), and auth/cimd.py is the fallback for a client that
identifies itself by a URL client id. A module here cannot import server.py, which imports it: the routes are registered by `signin.register(mcp)`, which server.py calls where
the routes were declared."""
