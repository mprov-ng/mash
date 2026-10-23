---
type: Architecture
title: mash Architecture Overview
description: How mash starts, chooses its command source, connects to the mProv Control Center, resolves config files, executes CRUD commands over HTTP, and dispatches unknown commands to plugins.
resource: src/mash/app.py
tags: [architecture, shell, mprov, plugins, http]
---

# mash Architecture Overview

mash is a single-process Python application built on the standard library's
[`cmd.Cmd`](https://docs.python.org/3/library/cmd.html) class. Everything
happens inside one shell object that holds the connection to the mProv Control
Center (mPCC), the session variables, and the loaded data models.

## Startup and command source

The installed `mash` command is a bash wrapper
([`src/mash/mash`](../../src/mash/mash)) that checks the Python version is
≥ 3.8 and then runs `python -m mash.main`.

[`mash.main`](../../src/mash/main.py) installs no-op SIGINT/SIGTERM handlers,
creates a single `MprovShell`, and picks the command source with bash/python-like
precedence:

1. A script file as `sys.argv[1]` (anything other than `-`) is opened and used,
   even when stdin is a pipe. A missing/unreadable file exits with
   `mash: <path>: <error>`.
2. `-` as the only argument, or a non-TTY stdin, means read commands from stdin.
3. Otherwise run the interactive shell.

This precedence is pinned by a regression test, see
[Development, Testing, and CI](../development-and-testing.md) (issue #9).

## The shell loop

`MprovShell` ([`src/mash/app.py`](../../src/mash/app.py)) overrides `cmdloop`
so script/stdin mode iterates lines directly (with `quiet = True`, suppressing
the `OK` echoes), while interactive mode uses `Cmd.cmdloop`. `precmd` strips
`#` comments, collects lines into the pending `foreach` body while inside a
loop, and otherwise renders each line through Jinja2 against the shell's
internal variables — so `{{ var }}` templating works on every command line.

Commands are the `do_*` methods: `connect`/`disconnect`, CRUD commands
(`create`/`retrieve`/`update`/`delete` with `post`/`get`/`patch`/`delete`
aliases), variable commands (`let`, `pvar`/`p`, `print`), loop commands
(`foreach`/`endforeach`, `seq`), and model inspection (`models`, `model`).

## Connecting and config lookup

`do_connect` supports three auth forms plus a config-file form; malformed
argument shapes print a usage error instead of raising (issue #15):

- `connect <url> apikey <key>` → `Api-Key` header
- `connect <url> user <user> password <pw>` or `connect <url> user <user>` →
  HTTP Basic auth; the no-password form prompts with `getpass` only when stdin
  is a TTY, and errors clearly otherwise
- `connect` (no args) → reads `mprovURL` and `apikey` from the `global` section
  of the first readable config file among, in order:
  `~/.mprov-mash.yaml`, `/etc/mprov/mash.yaml`, `/etc/mprov/jobserver.yaml`
  (the job server's own config, added for issue #4). When none is readable, the
  error lists each path tried and why it was skipped (issue #7). Config parsing
  accepts the job server's multi-document list shape and stubs its `!include`
  tag.

On a successful connection, `_connectToMPCC` GETs the base URL; on 200 it calls
`_getMPCCModels`, which pulls `/datamodel/` and then each model's structure
from `/datamodel/?model=<name>` into `self.models`. These models drive argument
validation for later CRUD commands.

## CRUD and HTTP

All data commands funnel through `_sendHttpRequest(method, arg, ...)`:

- The first token is the model name; it must exist in `self.models` and have an
  `endpoint`, otherwise the command errors without an HTTP call.
- `post`/`patch` parse `key=value` args, validate keys against the model's
  `fields`, check required fields (for `create`), and send JSON. `id`/`pk`
  become part of the URL path instead of the body.
- `get`/`delete` build a query string; `id=`/`pk=` also become a URL path
  segment.
- A trailing `&` forks the process so the request runs in the background; the
  parent tracks the pid in `self.processes` and `disconnect` waits for them.
  Backgrounded requests never set `MPROV_RESULT`.
- Successful responses set the internal variable `MPROV_RESULT` to the parsed
  JSON (or `None` on error), which scripts then read with `pvar` or `$var`
  copies in `let`.

Values passed as `[a,b]` are parsed into lists via `_parseArgType`; dict values
(`{...}`) are explicitly unsupported.

## Plugin dispatch

`MprovShell.default` treats any unrecognized command as a plugin name: it looks
up `mash.plugins.<name>` with `importlib`, instantiates the module's
`PluginCMD` class (a `cmd.Cmd` subclass receiving the shell instance), and
routes the rest of the line to it via `onecmd`. `help` with no arguments lists
the plugin files found in `src/mash/plugins/`, and `help <plugin>` delegates to
the plugin's own help.

The one shipped plugin is [`bmc`](../../src/mash/plugins/bmc.py): `bmc power
<on|off|cycle|reset> <node_spec>` sends `GET power/<action>/?hostname=<node>`
per node, expanding Slurm-style node ranges like `compute00[01-20,23]` with
`rangeToList` from [`mash.utils`](../../src/mash/utils.py).

## Utilities

`mash.utils` holds two pure helpers: `getDottedStrValue` (dotted-path lookup on
nested dicts) and `rangeToList` (Slurm node-range expansion, with padded-zero
validation). Both are plugin-facing; the core shell currently uses only
`rangeToList` indirectly through `bmc`.

## Gotchas

- `MprovShell` defines class-level mutable attributes (`variables`, `models`,
  `processes`, `session`). Creating a second instance shares them; tests work
  around this by mutating the fixture instance.
- `renderString` catches template errors but references `e.message`, which does
  not exist on modern exceptions — a template failure during `precmd` can raise
  `AttributeError` instead of the intended message.
- HTTP calls use `timeout=None`; a hanging mPCC blocks the shell (except for
  `&`-backgrounded requests).
