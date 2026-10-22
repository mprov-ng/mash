"""How mash chooses where to read commands from (mprov-ng/mash#9).

A script file on the command line wins, then a non-TTY stdin, then the
interactive shell.  '-' means stdin.
"""
import os
import pty
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
WRAPPER = SRC / "mash" / "mash"
BANNER = "Welcome to the mProv shell."


def env():
  e = dict(os.environ)
  e["PYTHONPATH"] = str(SRC) + os.pathsep + e.get("PYTHONPATH", "")
  return e


def mash(*args, stdin=subprocess.DEVNULL, input=None):
  return subprocess.run(
    [sys.executable, "-m", "mash.main", *args],
    stdin=stdin if input is None else None, input=input,
    capture_output=True, text=True, env=env(), timeout=30,
  )


@pytest.fixture
def script(tmp_path):
  path = tmp_path / "hello.mash"
  path.write_text("#!/usr/bin/env mash\nprint from-script-file\n")
  return path


def test_script_file_wins_over_piped_stdin(script):
  r = mash(str(script), input="print from-stdin\n")
  assert r.returncode == 0
  assert r.stdout == "from-script-file\n"


def test_script_file_wins_over_empty_pipe(script):
  r = mash(str(script), input="")
  assert r.returncode == 0
  assert r.stdout == "from-script-file\n"


def test_script_file_with_stdin_from_devnull(script):
  r = mash(str(script))
  assert r.returncode == 0
  assert r.stdout == "from-script-file\n"


def test_piped_stdin_without_a_file():
  r = mash(input="print from-stdin\n")
  assert r.returncode == 0
  assert r.stdout == "from-stdin\n"


def test_dash_reads_stdin():
  r = mash("-", input="print from-stdin\n")
  assert r.returncode == 0
  assert r.stdout == "from-stdin\n"


def test_stdin_redirected_from_a_regular_file_is_script_mode(tmp_path):
  # Used to start the interactive shell, with its banner and prompt.
  cmds = tmp_path / "cmds.txt"
  cmds.write_text("print from-file-stdin\n")
  with open(cmds) as f:
    r = mash(stdin=f)
  assert r.returncode == 0
  assert r.stdout == "from-file-stdin\n"


def test_missing_script_file_is_an_error(tmp_path):
  # Used to ignore the missing file and run stdin, or start the shell.
  missing = tmp_path / "nosuchfile"
  r = mash(str(missing), input="print from-stdin\n")
  assert r.returncode == 1
  assert r.stdout == ""
  assert f"mash: {missing}: No such file or directory" in r.stderr


def test_tty_starts_the_interactive_shell():
  leader, follower = pty.openpty()
  try:
    p = subprocess.Popen(
      [sys.executable, "-m", "mash.main"],
      stdin=follower, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
      text=True, env=env(),
    )
    os.write(leader, b"print from-tty\nexit\n")
    out, _ = p.communicate(timeout=30)
  finally:
    os.close(follower)
    os.close(leader)
  assert p.returncode == 0
  assert BANNER in out
  assert "from-tty" in out


def test_wrapper_passes_a_path_with_spaces(tmp_path):
  d = tmp_path / "dir with spaces"
  d.mkdir()
  path = d / "hello.mash"
  path.write_text("print from-script-file\n")
  r = subprocess.run(
    ["bash", str(WRAPPER), str(path)], stdin=subprocess.DEVNULL,
    capture_output=True, text=True, env=env(), timeout=30,
  )
  assert r.returncode == 0
  assert r.stdout == "from-script-file\n"
