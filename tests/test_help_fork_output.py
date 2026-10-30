"""Two output bugs (mprov-ng/mash#78).

'help <plugin> <cmd>' printed "*** No help on <plugin> <cmd>" and an echo
of its argument before the plugin's help.  And a backgrounded ('... &')
command forked with stdout still buffered, so the child printed
everything before it a second time when it exited.
"""
import os
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

from mash.app import MprovShell

SRC = Path(__file__).resolve().parent.parent / "src"


@pytest.fixture
def shell():
  s = MprovShell(stdin=StringIO(), stdout=StringIO())
  s.mprovURL = ""
  s.variables = {}
  return s


@pytest.mark.parametrize("command", ["help bmc power", "help bmc"])
def test_plugin_help_has_no_spurious_lines(shell, command):
  shell.onecmd(command)
  out = shell.stdout.getvalue()
  assert "No help on" not in out
  assert command[len("help "):] not in out.splitlines()
  if command == "help bmc power":
    assert out.lstrip().startswith("Manage the power of a node")


def test_builtin_help_is_not_echoed(shell):
  shell.onecmd("help connect")
  out = shell.stdout.getvalue()
  assert "Connect to an mProv Control Center." in out
  assert "connect" not in [line.strip() for line in out.splitlines()]


def test_unknown_help_topic_still_says_so(shell):
  shell.onecmd("help nosuchthing")
  assert "No help on nosuchthing" in shell.stdout.getvalue()


def test_background_command_does_not_repeat_buffered_output():
  # without the mash wrapper's PYTHONUNBUFFERED, a piped stdout is block
  # buffered, which is what the child used to inherit and print again.
  e = dict(os.environ)
  e.pop("PYTHONUNBUFFERED", None)
  e["PYTHONPATH"] = str(SRC) + os.pathsep + e.get("PYTHONPATH", "")
  r = subprocess.run(
    [sys.executable, "-m", "mash.main"],
    input="print before\nnosuchcommand &\nprint after\ndisconnect\n",
    capture_output=True, text=True, env=e, timeout=30,
  )
  # the failed background command makes the script exit 1 (#32)
  assert r.returncode == 1
  assert r.stdout.count("before") == 1
  assert r.stdout.count("after") == 1
