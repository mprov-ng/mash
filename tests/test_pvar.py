"""pvar must print comma-separated lists of multi-character variables.

'mash' documents pvar as taking "a comma separated list of variables"
(mprov-ng/mash#27): csv.reader fed the raw argument string iterated it
character-by-character, so 'pvar foo,bar' printed nothing.
"""
import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"


def env():
  e = dict(os.environ)
  e["PYTHONPATH"] = str(SRC) + os.pathsep + e.get("PYTHONPATH", "")
  return e


def mash(*args, input=None):
  return subprocess.run(
    [sys.executable, "-m", "mash.main", *args],
    input=input, capture_output=True, text=True, env=env(), timeout=30,
  )


def test_pvar_single_multichar_name():
  r = mash(input="let foo=1\npvar foo\n")
  assert r.returncode == 0
  assert "foo=1\n" in r.stdout


def test_pvar_comma_list_prints_all_multichar_names():
  r = mash(input="let foo=1\nlet bar=2\npvar foo,bar\n")
  assert r.returncode == 0
  assert "foo=1\n" in r.stdout
  assert "bar=2\n" in r.stdout


def test_pvar_comma_list_strips_whitespace_around_names():
  r = mash(input="let foo=1\nlet bar=2\npvar foo, bar\n")
  assert r.returncode == 0
  assert "foo=1\n" in r.stdout
  assert "bar=2\n" in r.stdout
