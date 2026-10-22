"""The command-line forms of 'connect' (mprov-ng/mash#15)."""
import base64

import pytest

from mash.app import MprovShell

USAGE = "Usage: connect"


def basic(user, password):
  return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


@pytest.fixture
def shell(monkeypatch, tmp_path):
  s = MprovShell()
  s.mprovURL = ""
  # no config files, so a bare 'connect' fails rather than reading /etc/mprov.
  s.configfiles = [str(tmp_path / "missing.yaml")]
  s.connected = []
  monkeypatch.setattr(s, "_connectToMPCC", lambda header: s.connected.append(header))
  return s


@pytest.fixture
def tty(monkeypatch):
  'Make stdin look like a terminal, and answer the password prompt.'
  monkeypatch.setattr("sys.stdin.isatty", lambda: True)
  prompts = []
  def fake_getpass(prompt):
    prompts.append(prompt)
    return "s3cret"
  monkeypatch.setattr("getpass.getpass", fake_getpass)
  return prompts


def test_apikey(shell):
  shell.onecmd("connect http://mpcc/ apikey abc123")
  assert shell.connected == ["Api-Key abc123"]
  assert shell.mprovURL == "http://mpcc/"


def test_user_and_password(shell):
  shell.onecmd("connect http://mpcc/ user alice password s3cret")
  assert shell.connected == [basic("alice", "s3cret")]
  assert shell.mprovURL == "http://mpcc/"


def test_username_user_is_not_special(shell):
  # The old code only recognised the 'user' keyword when the username was 'user'.
  shell.onecmd("connect http://mpcc/ user user password pw")
  assert shell.connected == [basic("user", "pw")]


def test_extra_spaces_are_ignored(shell):
  shell.onecmd("connect  http://mpcc/   apikey  abc123 ")
  assert shell.connected == ["Api-Key abc123"]


def test_password_prompt_on_a_tty(shell, tty):
  shell.onecmd("connect http://mpcc/ user alice")
  assert tty == ["Password for alice: "]
  assert shell.connected == [basic("alice", "s3cret")]
  assert shell.mprovURL == "http://mpcc/"


def test_eof_at_the_password_prompt_cancels(shell, monkeypatch):
  monkeypatch.setattr("sys.stdin.isatty", lambda: True)
  def eof(prompt):
    raise EOFError
  monkeypatch.setattr("getpass.getpass", eof)
  shell.onecmd("connect http://mpcc/ user alice")
  assert shell.connected == []
  assert shell.mprovURL == ""


def test_no_password_without_a_tty_is_an_error(shell, monkeypatch, capsys):
  monkeypatch.setattr("sys.stdin.isatty", lambda: False)
  shell.onecmd("connect http://mpcc/ user alice")
  assert shell.connected == []
  assert shell.mprovURL == ""
  assert "no password given" in capsys.readouterr().err


@pytest.mark.parametrize("args", [
  "http://mpcc/",                                   # no credentials
  "http://mpcc/ apikey",                            # no key
  "http://mpcc/ apikey abc123 extra",
  "http://mpcc/ user",                              # no username
  "http://mpcc/ user alice password",               # no password after the keyword
  "http://mpcc/ user alice pass s3cret",            # wrong keyword
  "http://mpcc/ user alice password s3cret extra",
  "http://mpcc/ token abc123",
])
def test_malformed_commands_print_usage_and_do_not_connect(shell, args, capsys):
  shell.onecmd(f"connect {args}")
  assert shell.connected == []
  assert shell.mprovURL == ""
  assert USAGE in capsys.readouterr().err


def test_no_arguments_still_reads_the_config(shell, capsys):
  shell.onecmd("connect")
  assert shell.connected == []
  assert "Unable to find a readable config file." in capsys.readouterr().err
