"""'bmc power' must report per-node results (mprov-ng/mash#25).

The plugin used to discard the power API response entirely, so
'bmc power cycle compute001' printed nothing whether the mPCC succeeded
or failed.  Each node now gets one result line on stdout, and any
failure is surfaced on stderr as a command-level error.
"""
import io
import pytest

from mash.app import MprovShell
from mash.plugins.bmc import PluginCMD


class FakeResponse:
  def __init__(self, status_code=200, text="cycle requested"):
    self.status_code = status_code
    self.text = text


class FakeSession:
  'Records the power URLs fetched and replays a canned response per node.'
  def __init__(self, responses):
    self.responses = responses
    self.urls = []

  def get(self, url, **kwargs):
    self.urls.append(url)
    node = url.split("hostname=")[1]
    response = self.responses[node]
    if isinstance(response, Exception):
      raise response
    return response


@pytest.fixture
def shell():
  s = MprovShell()
  s.mprovURL = "http://mpcc/api/"
  s.stdout = io.StringIO()
  return s


def run_power(shell, arg):
  PluginCMD(shell).onecmd("power " + arg)


def test_success_prints_node_result_line(shell, capsys):
  shell.session = FakeSession({"compute001": FakeResponse(text="cycle requested")})
  run_power(shell, "cycle compute001")
  out = shell.stdout.getvalue()
  assert "compute001: cycle requested" in out


def test_http_error_prints_error_line_and_fails_command(shell, capsys):
  shell.session = FakeSession({"compute001": FakeResponse(500, "power daemon down")})
  run_power(shell, "cycle compute001")
  captured = capsys.readouterr()
  out = shell.stdout.getvalue()
  assert "compute001" in out
  assert "500" in out
  assert "power daemon down" in out
  # command-level failure signal for scripts: non-empty stderr.
  assert captured.err.strip() != ""


def test_every_node_in_range_gets_a_line(shell, capsys):
  shell.session = FakeSession({
    "compute001": FakeResponse(),
    "compute002": FakeResponse(404, "unknown hostname"),
    "compute003": OSError("connection refused"),
  })
  run_power(shell, "cycle compute00[1-3]")
  captured = capsys.readouterr()
  out = shell.stdout.getvalue()
  # all three were fetched, and a dead node does not abort the rest.
  assert len(shell.session.urls) == 3
  assert "compute001" in out
  assert "compute002" in out
  assert "compute003" in out
  # HTTP error and transport error both surface.
  assert "404" in out
  assert "connection refused" in out
  assert captured.err.strip() != ""


def test_all_success_leaves_stderr_clean(shell, capsys):
  shell.session = FakeSession({
    "compute001": FakeResponse(),
    "compute002": FakeResponse(),
  })
  run_power(shell, "on compute00[1-2]")
  captured = capsys.readouterr()
  out = shell.stdout.getvalue()
  assert "compute001" in out
  assert "compute002" in out
  assert captured.err.strip() == ""
