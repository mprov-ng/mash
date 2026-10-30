---
type: Reference
title: mash Quickstart
description: Entry point for the mash (mProv Admin Shell) wiki — what the tool is, how to install and run it, its command surface, and where to find architecture, development, and testing documentation.
resource: src/mash/main.py
tags: [quickstart, mprov, shell, cli]
---

# mash (mProv Admin Shell)

mash is the command-line utility for talking to the [mProv Control Center
(mPCC)](https://github.com/mprov-ng/). It is simultaneously an interactive
shell (a Python `cmd.Cmd` loop with its own variables, Jinja2 templating, and
`foreach` loops) and a script runner: you can pipe a script into it or pass a
script file on the command line.

## Install and run

Requires Python 3.8+. From a checkout, install the package — this pulls the
three dependencies (`pyyaml`, `jinja2`, `requests`) and puts `mash` on your
PATH:

```bash
pip install .
mash                           # interactive shell
mash script.mash               # run a script file (wins over piped stdin)
some-tool | mash               # read commands from piped stdin
```

To work without installing (e.g. in a source checkout), install the
requirements and point Python at the src layout:

```bash
pip install -r requirements.txt
PYTHONPATH=src python -m mash.main
```

The installed `mash` command is a bash wrapper that checks the version of the
first `python3` on your PATH and runs `python -m mash.main`, so install into
the environment whose `bin/` comes first on PATH (a virtualenv you have
activated is the usual case).

## First commands

```text
<mProv> # connect https://mpcc.example/ apikey <key>
<mProv> # models                  # list data models fetched from the mPCC
<mProv> # retrieve node id=1      # GET; result lands in MPROV_RESULT
<mProv> # pvar MPROV_RESULT
<mProv> # create node name=compute001 ...
<mProv> # bmc power on compute00[01-05]   # plugin command
```

`connect` with no arguments reads `mprovURL` and `apikey` from the first
readable config file among `~/.mprov-mash.yaml`, `/etc/mprov/mash.yaml`, and
`/etc/mprov/jobserver.yaml`. A trailing `&` on a data command runs the request
in the background. Comments start with `#`; `{{ var }}` templates are rendered
against variables set with `let`.

Two shell modes help scripting: `output json` prints each result as one line
of compact JSON, and `dryrun on` prints the changes a command would make
instead of sending them (reads still go through). The `--json` / `--dry-run`
CLI flags start a session in those modes. A script exits 1 if any of its
commands failed; errors and warnings go to stderr, results to stdout. The
[README](../README.md) is the full user reference for every command.

## Where to go next

- [Architecture overview](architecture/overview.md) — startup and command-source
  precedence, the shell loop, connect/config lookup, CRUD-to-HTTP mapping, and
  the plugin system behind commands like `bmc`.
- [Development, testing, and CI](development-and-testing.md) — dev install, the
  pytest suite and the issue regressions each file pins, and the GitHub Actions
  workflows.

## Backlog

- Plugin authoring guide — only one plugin (`src/mash/plugins/bmc.py`) exists;
  the `PluginCMD` contract is documented inline in the architecture page until
  a second plugin establishes a pattern.
- Shell scripting edge cases (`seq`, `let` backticks, nested `foreach`) —
  `foreach` list/comment handling is now covered by `tests/test_foreach.py`,
  but these remaining behaviors are documented from source/README only.
