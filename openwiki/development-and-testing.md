---
type: Playbook
title: Development, Testing, and CI
description: How to install mash for development, run the pytest suite, what the GitHub Actions workflows check (including the scheduled OpenWiki update workflow and tests.yml paths-ignore for agent instruction files), the agent working rules in AGENTS.md, and the behaviors pinned by the regression tests for connect auth, config lookup, and script/stdin precedence.
resource: .github/workflows/tests.yml
tags: [testing, ci, packaging, pytest, github-actions]
---

# Development, Testing, and CI

## Install for development

Python ≥ 3.8 is required (the `mash` wrapper enforces this at runtime). From
the repo root:

```bash
pip install -r requirements.txt   # pyyaml, jinja2, requests
pip install pytest
```

`pyproject.toml` sets `pythonpath = ["src"]` for pytest, so tests import
`mash.*` directly from the source tree without an install step. Packaging
metadata lives in `setup.cfg` (package `mprov_mash`, src layout) with the
`mash` script declared as `src/mash/mash`; the version comes from the `VERSION`
file (falling back to the `MASH_VERSION` environment variable at build time),
consumed by `setup.py`.

## Test suite

Run with `pytest` from the repo root. Each test file pins a regression from a
filed issue:

- [`tests/test_connect.py`](../../tests/test_connect.py) — the argument forms of
  `connect` (issue #15): apikey form, user+password form, TTY password prompt
  (including `^D` cancelling), the non-TTY-without-password error, rejection of
  malformed arg shapes with a usage message, and the no-arg config-file form.
- [`tests/test_config.py`](../../tests/test_config.py) — config file lookup for
  bare `connect` (issue #7): preference order of `~/.mprov-mash.yaml`,
  `/etc/mprov/mash.yaml`, `/etc/mprov/jobserver.yaml`; skipping unreadable or
  missing files with per-path reasons in the error; tolerating the job server's
  `!include` YAML tag.
- [`tests/test_main.py`](../../tests/test_main.py) — command source precedence
  in `mash.main` (issue #9): a script file argument wins over piped stdin, `-`
  means stdin, and a TTY stdin gets the interactive banner. Runs the real
  module as a subprocess with `PYTHONPATH=src`.

When changing `do_connect`, `load_config`, or `main.py`'s startup logic — the
areas explained in the [architecture overview](architecture/overview.md) — run
these three files first; they encode the intended error messages and precedence
rules. For shell-loop changes (templating, foreach, HTTP plumbing) there is
currently no test coverage; exercise behavior manually or add tests.

## CI workflows

- [`../../.github/workflows/tests.yml`](../../.github/workflows/tests.yml) — pytest on pushes
  and PRs to `master`, matrixed over Python 3.9 (Rocky 9's system Python), 3.11,
  and 3.13. Pushes/PRs that only touch `AGENTS.md` or `CLAUDE.md` are skipped
  via `paths-ignore`, since agent instructions can't affect the tests.
- `.github/workflows/ci.yml` — builds the Python module and Docker image on
  published releases; runs as a dry run (everything but publish) on PRs that
  touch build files.
- `.github/workflows/openwiki-update.yml` — runs `openwiki code --update --print`
  on a daily schedule (or manually via `workflow_dispatch`) and opens a pull
  request with the regenerated `openwiki/` pages; `openwiki/.last-update.json`
  records the HEAD the pages were generated against.
- `.github/dependabot.yml` — Dependabot updates for GitHub Actions.

## Agent instructions (`AGENTS.md`)

`AGENTS.md` at the repo root holds the working rules shared across the
mprov-ng repos (mPCC, jobserver, scripts, mash), and `CLAUDE.md` imports it
(`@AGENTS.md`) so both agent tools read the same copy. Key rules: cut every
branch from a freshly fetched default branch with `--no-track`; end agent
commits with an `Assisted-By: <model> <noreply@anthropic.com>` trailer
(never `Co-Authored-By`, never `-s`); show the maintainer the commits and get
an explicit go-ahead before any push; treat the mPCC REST API as a contract —
check how the client repos use an endpoint before changing it (and vice versa);
record new bugs/follow-ups as GitHub issues; and background-watch dependent
PRs until they merge. OpenWiki maintains a marked block (`OPENWIKI:START`/
`OPENWIKI:END`) inside both files — leave the surrounding hand-written rules
alone when regenerating docs.

## Release versioning

The version is the contents of `VERSION`, and `gen_changelog.sh` at the repo
root generates changelog text from git history for release notes.
