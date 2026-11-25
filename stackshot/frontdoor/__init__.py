"""The front door: one MCP endpoint over several stackshot boards and a brain.

A reverse proxy in front of it checks who is calling and sets one header; the front door lists the tools of the boards (and the brain) that member is on as
ONE tool set, routes each call to the board it names, and calls every backend with its own credential and the caller's signed identity. See
docs/front-door.md.

    python -m stackshot.frontdoor            serve, with the settings of the config file's [frontdoor] table
    python -m stackshot.frontdoor --check    read the settings, print the config notes and the backends, and exit (0: the front door could start)

This package is its own program. The board server imports nothing of it, and importing the package imports nothing (fastmcp is loaded by the
modules that need it: `app`, `backend`, `provider`, `instructions`), so a machine without the `server` extra can still load the config.
"""
