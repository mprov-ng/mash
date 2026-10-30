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

[`mash.main`](../../src/mash/main.py) creates a single `MprovShell`, consumes
leading `--json` / `--dry-run` flags (see
[Output modes and dry runs](#output-modes-and-dry-runs)), and picks the command
source with bash/python-like precedence:

1. A script file as `sys.argv[1]` (anything other than `-`) is opened and used,
   even when stdin is a pipe. A missing/unreadable file exits with
   `mash: <path>: <error>`.
2. `-` as the only argument, or a non-TTY stdin, means read commands from stdin.
3. Otherwise run the interactive shell.

This precedence is pinned by a regression test, see
[Development, Testing, and CI](../development-and-testing.md) (issue #9).

SIGINT/SIGTERM keep Python's default handling so a hung request can always be
interrupted (issue #30): Ctrl-C in a script stops it with exit status 130,
while the interactive shell turns Ctrl-C into "back to the prompt". In script
mode the exit status is `scriptStatus()` — 1 if any command (including
backgrounded ones) failed, 0 otherwise; warnings don't count (issue #32).
Errors and warnings go to stderr via `MprovShell.err()`, results and `print`
output to stdout via `print()` (issue #31).

## Output modes and dry runs

Two shell-level switches change what every command does; both are class
attributes on `MprovShell` set from the CLI flags or the `output` / `dryrun`
commands:

- `outputMode` (`output json` | `output text`, `mash --json`): in `json` mode,
  data commands print the parsed reply as one line of compact JSON
  (`printJSON`), `models` prints a list, and `model`/`pvar` print objects.
  Errors still go to stderr (issue #42).
- `dryRun` (`dryrun on` | `dryrun off`, `mash --dry-run`): `create`, `update`,
  `delete` and every `bmc power` action except `status` print the request they
  would send instead of sending it, and set `MPROV_RESULT` to `None`. Reads
  (`retrieve`, `bmc power status`) still go through, so scripts can preview a
  loop over real results (issue #43).

## Timeouts and signals

Every mPCC call goes through `TimeoutSession`, a `requests.Session` whose
default `(connect, read)` timeout is `(10, 120)` seconds; the optional
`timeout` key in a config file's `global` section overrides the read part
(issue #29). The connection adapter retries failed connections but never a
read timeout (`Retry(total=20, read=0)`), so a hung mPCC can't hold every
request for 21 timeouts.

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
(`foreach`/`endforeach`, `seq`), model inspection (`models`, `model`), and mode
switches (`output`, `dryrun`; see
[Output modes and dry runs](#output-modes-and-dry-runs)).

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
  tag. `_checkConfigKeys` then requires `mprovURL` and `apikey` and warns on
  unknown keys/sections in mash's own files (suggesting the key you probably
  meant), but leaves `jobserver.yaml` keys unchecked since the job server has
  its own (issue #44). `mprovURL` is stored without a trailing slash; callers
  add the slash they need (issue #24).

On a successful connection, `_connectToMPCC` GETs the base URL; on 200 it calls
`_getMPCCModels`, which pulls `/datamodel/` and then each model's structure
from `/datamodel/?model=<name>` into `self.models`. These models drive argument
validation for later CRUD commands. A 401/403 from the base URL — the mPCC's
`/` requires login — errors with a hint to check the API key or credentials
(issue #38).

## CRUD and HTTP

All data commands funnel through `_sendHttpRequest(method, arg, ...)`:

- The first token is the model name; it must exist in `self.models` and have an
  `endpoint`, otherwise the command errors without an HTTP call.
- `post`/`patch` parse `key=value` args, validate keys against the model's
  `fields`, check required fields (for `create`), and send JSON. `id`/`pk`
  become part of the URL path instead of the body.
- `get`/`delete` pass every other `key=value` as request params, so `&`, `#`
  and `%` in a value stay inside it (issues #19, #36); a query key that is
  neither a model field nor one of the extra keys the mPCC reads
  (`self.queryKeys`: `detail`, `search`, `hostname`, `network`, `status`,
  `powerstate`, ...) still gets sent but produces a warning, because older
  mPCCs ignore unknown filters and return every row.
- A trailing `&` forks the process so the request runs in the background; the
  parent tracks the pid in `self.processes` and scripts wait for them before
  exiting (`_waitForBackground`). Backgrounded requests never set
  `MPROV_RESULT`, and a nonzero child exit marks the script as failed.
- Non-2xx or transport errors go through `_httpErrorExit`, which clears
  `MPROV_RESULT` so a failed command can't leave the previous result behind
  (issue #26). An empty 2xx body (e.g. a successful 204 delete) parses to
  `None` rather than a JSON error (issue #69). On success `MPROV_RESULT` is
  the parsed JSON, which scripts then read with `pvar` or `$var` copies in
  `let`.

Values passed as `[a,b]` are parsed into lists via `_parseArgType`; dict values
(`{...}`) are explicitly unsupported.

Templates render in Jinja2's `SandboxedEnvironment` with `StrictUndefined`: an
undefined name or broken template is an error and the command does not run, so
a missing id can't turn into `DELETE /systems//` (issue #57). Malformed
command lines print an error instead of crashing the shell (issue #28).

## Plugin dispatch

`MprovShell.default` treats any unrecognized command as a plugin name: it looks
up `mash.plugins.<name>` with `importlib`, instantiates the module's
`PluginCMD` class (a `cmd.Cmd` subclass receiving the shell instance), and
routes the rest of the line to it via `onecmd`. `help` with no arguments lists
the plugin files found in `src/mash/plugins/`, and `help <plugin>` delegates to
the plugin's own help.

The one shipped plugin, [`src/mash/plugins/bmc.py`](../../src/mash/plugins/bmc.py),
implements `bmc power <action> <node_spec>` with actions `on`, `off`, `cycle`,
`reset`, `status`, `pxe`, and `pxeefi` (unknown actions are refused),
expanding Slurm-style node ranges like `compute00[01-20,23]` with `rangeToList`
from [`mash.utils`](../../src/mash/utils.py). Each node gets one line — `OK`,
its status, or `ERROR <reason>` — and the command fails if any node failed
(issue #37). It respects the shell's switches: a trailing `&` runs it in the
background (`bmc` is dispatched through the same background mechanism as data
commands, issue #37), and with `dryrun on` every action except `status` prints
a `DRY RUN GET <url>` preview instead of calling the mPCC. Its "not connected"
error goes to stderr via `mashCmd.err()` (issue #55).

## Utilities

`mash.utils` holds two pure helpers: `getDottedStrValue` (dotted-path lookup on
nested dicts) and `rangeToList` (Slurm node-range expansion, with padded-zero
validation). Both are plugin-facing; the core shell currently uses only
`rangeToList` indirectly through `bmc`.

## Gotchas

- `MprovShell` defines class-level mutable attributes (`variables`, `models`,
  `processes`, `session`). Creating a second instance shares them; tests work
  around this by mutating the fixture instance.
