"""A malformed command must end that command, not the shell (mprov-ng/mash#28, #35).

Before, these raised out of cmd.Cmd and ended the session (or a piped
script) with a traceback, and a dict-shaped value called sys.exit(1).
"""
from io import StringIO

import pytest

from mash.app import MprovShell


class FakeSession:
  'Records every request instead of talking to an mPCC.'
  def __init__(self):
    self.requests = []

  def __getattr__(self, method):
    if method in ("get", "post", "patch", "delete"):
      return lambda url, **kwargs: self.requests.append((method, url))
    raise AttributeError(method)


@pytest.fixture
def shell():
  s = MprovShell(stdout=StringIO())
  s.variables = {"MPROV_RESULT": ["stale"]}
  s.quiet = True
  s.mprovURL = "http://mpcc"
  s.session = FakeSession()
  s.models = {"systems.models.System": {"endpoint": "/systems/",
                                        "fields": {"hostname": {"required": False}}}}
  return s


@pytest.mark.parametrize("line,message", [
  ("let foo", "Usage: let"),
  ("seq a 1 xx", "Usage: seq"),
  ("seq a 1", "Usage: seq"),
  ("seq a 1 3 w", "Usage: seq"),
  ("seq a", "Usage: seq"),
  ("create systems.models.System hostname={'a':1}", "dict values aren't supported"),
  ("create systems.models.System hostname", "expected <field>=<value>"),
  ("create systems.models.System hostname='unbalanced", "can't parse the arguments"),
])
def test_malformed_command_reports_and_the_shell_carries_on(shell, capsys, line, message):
  shell.onecmd(shell.precmd(line))
  assert message in capsys.readouterr().err
  assert shell.session.requests == []
  # the shell is still usable
  shell.onecmd("print still-alive")
  assert shell.stdout.getvalue().endswith("still-alive\n")


@pytest.mark.parametrize("line", [
  "create systems.models.System hostname={'a':1}",
  "create systems.models.System hostname",
])
def test_rejected_request_clears_the_result(shell, line):
  shell.onecmd(line)
  assert shell.variables["MPROV_RESULT"] is None


def test_empty_backtick_capture_assigns_an_empty_string(shell):
  # 'bmc power' while not connected prints only on stderr, so the capture is empty.
  shell.mprovURL = ""
  shell.onecmd("let y=`bmc power on node01")
  assert shell.variables["y"] == ""


def test_backtick_capture_is_assigned_as_is(shell):
  shell.variables["x"] = "1"
  shell.onecmd("let y=`print $x")
  assert shell.variables["y"] == "$x\n"


def test_seq_still_works(shell):
  shell.onecmd("seq n 8 10 3")
  assert shell.variables["n"] == ["008", "009", "010"]
  shell.onecmd("seq m 1 2")
  assert shell.variables["m"] == ["1", "2"]


def test_unexpected_error_ends_only_that_command(shell, capsys, monkeypatch):
  def boom(arg):
    raise RuntimeError("something nobody thought of")
  monkeypatch.setattr(shell, "do_print", boom)
  shell.onecmd("print anything")
  assert "Error: RuntimeError: something nobody thought of" in capsys.readouterr().err
  shell.onecmd("pvar MPROV_RESULT")
  assert "MPROV_RESULT=" in shell.stdout.getvalue()


def test_exit_still_exits(shell):
  with pytest.raises(SystemExit):
    shell.onecmd("exit")


def test_capture_restores_stdout_after_an_error(shell, monkeypatch):
  original = shell.stdout
  def boom(arg):
    raise RuntimeError("x")
  monkeypatch.setattr(shell, "do_print", boom)
  shell.onecmd("let y=`print hi")
  assert shell.stdout is original
