"""mprov-ng/mash#24: bmc power joined paths onto mprovURL blindly, so
'connect http://host:8080' (typed without a trailing slash) made every power
command fetch 'http://host:8080power/on/...' instead of '/power/on/...'.
connect now normalizes mprovURL to exactly one trailing slash."""
import pytest

from mash.app import MprovShell


class FakeResponse:
  status_code = 200
  text = "OK"

  def json(self):
    return {}


class FakeSession:
  'Records request URLs instead of talking to an mPCC.'

  def __init__(self):
    self.urls = []

  def get(self, url, **kwargs):
    self.urls.append(url)
    return FakeResponse()


@pytest.fixture
def shell(monkeypatch, tmp_path):
  s = MprovShell()
  s.configfiles = [str(tmp_path / "missing.yaml")]
  s.session = FakeSession()
  # Don't talk to a real mPCC; connect just stores what it was given.
  monkeypatch.setattr(s, "_connectToMPCC", lambda header: None)
  return s


def power_url(shell):
  shell.onecmd("bmc power on node01")
  return shell.session.urls[-1]


def test_power_url_when_connect_omitted_the_slash(shell):
  shell.onecmd("connect http://127.0.0.1:8080 apikey KEY")
  assert shell.mprovURL == "http://127.0.0.1:8080/"
  assert power_url(shell) == "http://127.0.0.1:8080/power/on/?hostname=node01"


def test_power_url_when_connect_included_the_slash(shell):
  shell.onecmd("connect http://127.0.0.1:8080/ apikey KEY")
  assert power_url(shell) == "http://127.0.0.1:8080/power/on/?hostname=node01"


def test_extra_trailing_slashes_are_collapsed(shell):
  shell.onecmd("connect http://127.0.0.1:8080// apikey KEY")
  assert shell.mprovURL == "http://127.0.0.1:8080/"
