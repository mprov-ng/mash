---
type: Playbook
title: Development, Testing, and CI
description: How to install mash for development, the bounded runtime dependencies and the minimum-version CI job, the pytest regression suite and what it pins (connect, config, timeouts, JSON/dry-run output, scripting, plugins), and the GitHub Actions workflows for tests, lint (ruff + ShellCheck), packaging, and OpenWiki updates, plus the agent working rules in AGENTS.md.
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

`requirements.txt` bounds each dependency (`PyYAML>=5.4.1,<7`,
`Jinja2>=2.11.3,<4`, `requests>=2.25.1,<3`); the lower bounds are Rocky 9's
system packages so mash installs next to them (issue #45).
[`tests/min-versions.txt`](../../tests/min-versions.txt) pins those same
versions (plus `MarkupSafe==1.1.1`, which Jinja2 2.11 needs) and
[`tests/test_requirements.py`](../../tests/test_requirements.py) fails if the
two files drift apart — keep them equal when touching either.

`pyproject.toml` sets `pythonpath = ["src"]` for pytest, so tests import
`mash.*` directly from the source tree without an install step. Packaging
metadata lives in `setup.cfg` (package `mprov_mash`, src layout) with the
`mash` script declared as `src/mash/mash`; the version comes from the `VERSION`
file (falling back to the `MASH_VERSION` environment variable at build time),
consumed by `setup.py`.

## Test suite

Run with `pytest` from the repo root. Each test file pins a regression from a
filed issue and covers one behavior of the areas explained in the
[architecture overview](architecture/overview.md):

- Connect and config: `test_connect.py` (arg forms, TTY prompt, malformed
  shapes, #15), `test_config.py` (config lookup order and per-path skip
  reasons, #7), `test_load_config.py` (mapping-shaped configs, clean config
  errors), `test_connect_checks.py` (refused connect, config key checks,
  #38/#44).
- HTTP and results: `test_timeouts_signals.py` (request timeouts, Ctrl-C /
  SIGTERM, #29/#30), `test_query_params.py` (query encoding, malformed
  tokens, #19/#36), `test_empty_reply.py` (empty 2xx as success, #69),
  `test_stale_result.py` (`MPROV_RESULT` cleared on error paths, #26),
  `test_background.py` (backgrounded children always exit).
- Output and preview modes: `test_json_output.py` (`output json` /
  `mash --json`, #42), `test_dry_run.py` (`dryrun on` / `mash --dry-run`,
  #43).
- Shell language: `test_render_sandbox.py` and `test_render_errors.py`
  (sandboxed templates; a failed render aborts the command, #57),
  `test_foreach.py` (list items containing `#`, quoted word lists, #48),
  `test_pvar.py` (comma-list `pvar`), `test_no_crash.py` (malformed commands
  don't kill the shell, #28/#35/#39).
- Scripts: `test_main.py` (command source precedence, #9),
  `test_script_status.py` (errors to stderr, exit 1 on failure, #31/#32).
- Plugins: `test_plugin_dispatch.py` (args containing the plugin name,
  #18), `test_plugin_output.py` (plugin help/errors routed through the
  shell, #25/#55), `test_bmc.py`, `test_bmc_power.py` (per-node results,
  #37/#41), `test_bmc_background.py` (`bmc ... &`, #37).
- Packaging: `test_requirements.py` (requirements/min-versions consistency,
  #45).

When changing `do_connect`, `load_config`, or `main.py`'s startup logic, run
the connect/config files first; they encode the intended error messages and
precedence rules. Each other area above has its own regression file — run the
matching group when touching templating, HTTP plumbing, output modes, or the
bmc plugin.

## CI workflows

- [`../../.github/workflows/tests.yml`](../../.github/workflows/tests.yml) — pytest on pushes
  and PRs to `master`, matrixed over Python 3.9 (Rocky 9's system Python), 3.11,
  and 3.13, plus a `minimum` variant that installs the 3.9 matrix leg against
  `tests/min-versions.txt` to prove the lower bounds work (#45).
  Pushes/PRs that only touch `AGENTS.md` or `CLAUDE.md` are skipped
  via `paths-ignore`, since agent instructions can't affect the tests.
- The same file's `lint` job (#46) runs `ruff check` (pinned version) with the
  errors-only rule selection from `pyproject.toml` (`E9`, `F63`, `F7`, `F82` —
  no style rules), and `shellcheck -S error` on `src/mash/mash` and
  `gen_changelog.sh`.
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
