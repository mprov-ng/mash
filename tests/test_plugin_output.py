"""Plugin help and diagnostics follow the shell's output stream (#20)."""
from io import StringIO

import pytest

from mash.app import MprovShell
from mash.plugins.bmc import PluginCMD


@pytest.fixture
def shell(monkeypatch):
  s = MprovShell(stdin=StringIO(), stdout=StringIO())
  s.mprovURL = ""
  s.variables = {}
  def no_request(*args, **kwargs):
    pytest.fail("plugin output tests must not make HTTP requests")
  monkeypatch.setattr(s.session, "get", no_request)
  return s


@pytest.mark.parametrize("command,expected", [
  ("help", "Loaded Plugins:"),
  ("help bmc power", "Manage the power of a node"),
  ("bmc help power", "Manage the power of a node"),
  ("bmc power on node01", "ERROR: You probably aren't connected."),
])
def test_plugin_output_uses_shell_stdout(shell, capsys, command, expected):
  shell.onecmd(command)
  assert expected in shell.stdout.getvalue()
  assert capsys.readouterr().out == ""


def test_plugin_uses_shell_streams(shell):
  plugin = PluginCMD(shell)
  assert plugin.stdin is shell.stdin
  assert plugin.stdout is shell.stdout


def test_backtick_assignment_captures_plugin_help(shell, capsys):
  original_stdout = shell.stdout
  shell.onecmd("let captured=`bmc help power")
  assert "Manage the power of a node" in shell.variables["captured"]
  assert shell.stdout is original_stdout
  assert shell.stdout.getvalue() == ""
  assert capsys.readouterr().out == ""


def test_internal_capture_includes_plugin_list(shell, capsys):
  output = shell.execInternal("help")
  assert "Loaded Plugins:" in output
  assert "bmc" in output
  assert shell.stdout.getvalue() == ""
  assert capsys.readouterr().out == ""
