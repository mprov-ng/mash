"""A line whose template fails to render must not run (mprov-ng/mash#57).

Before, renderString printed an error and returned the raw template text,
which then ran as the command, and an undefined name rendered as "".  So
'delete ... id={{ nodeId }}' with nodeId unset sent 'DELETE /systems//?id=&'.
"""
from io import StringIO

import pytest

from mash.app import MprovShell


class FakeResponse:
  status_code = 200
  text = "{}"

  def json(self):
    return {}


class FakeSession:
  'Records every request instead of talking to an mPCC.'
  def __init__(self):
    self.requests = []

  def _record(self, method):
    def call(url, **kwargs):
      self.requests.append((method, url))
      return FakeResponse()
    return call

  def __getattr__(self, method):
    if method in ("get", "post", "patch", "delete"):
      return self._record(method)
    raise AttributeError(method)


@pytest.fixture
def shell():
  s = MprovShell(stdout=StringIO())
  s.variables = {}
  s.quiet = True
  s.mprovURL = "http://mpcc"
  s.session = FakeSession()
  s.models = {"systems.models.System": {"endpoint": "/systems/", "fields": {}}}
  return s


def run(shell, line):
  'Run a line the way the shell does: render in precmd, then dispatch.'
  shell.onecmd(shell.precmd(line))


@pytest.mark.parametrize("line", [
  "delete systems.models.System id={{ nodeId }}",        # undefined name
  "delete systems.models.System id={{ x.y }}",           # attribute of an undefined name
  "delete systems.models.System id={{ ''.__class__ }}",  # attribute the sandbox refuses
  "delete systems.models.System id={{ 1/0 }}",           # any other render exception
  "delete systems.models.System id={{ nodeId",           # template syntax error
])
def test_failed_render_does_not_send_the_request(shell, capsys, line):
  run(shell, line)
  assert shell.session.requests == []
  assert "Error trying to template" in capsys.readouterr().err


def test_render_error_is_reported_on_stderr_not_stdout(shell, capsys):
  run(shell, "print {{ 1/0 }}")
  assert shell.stdout.getvalue() == ""
  err = capsys.readouterr().err
  assert "Error trying to template" in err
  assert "division by zero" in err


def test_defined_names_still_render(shell):
  shell.variables["nodeId"] = "7"
  run(shell, "delete systems.models.System id={{ nodeId }}")
  assert shell.session.requests == [("delete", "http://mpcc/systems/7/?id=7&")]


def test_render_error_in_a_loop_stops_the_loop(shell, capsys):
  for line in ["foreach n in 1 2 3", "print a{{n}}", "print {{ nope }}", "endforeach"]:
    run(shell, line)
  # the first command ran once, then the loop stopped at the failed render
  assert shell.stdout.getvalue() == "a1\n"
  err = capsys.readouterr().err
  assert "Error trying to template" in err
  assert "Error running loop." in err
  assert not shell.inForLoop
  assert shell.forLoopCmds == []
