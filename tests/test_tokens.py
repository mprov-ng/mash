"""Per-user API tokens (mprov-ng/mash#86, mprov_control_center#502).

'connect <url> token <token>' and 'token:' in the config send
"Authorization: Token <token>".  The mPCC's / answers without a login, so
connect checks a token with GET /tokens/ and reports the mPCC's reason for
refusing it (revoked, expired, a version mismatch) straight away.

'connect <url> user <user> ... save-token [<name>]' makes a token with
the user's password (POST /tokens/) and connects with it.  It writes the
token to ~/.mprov-mash.yaml only if that file doesn't exist yet, and
otherwise shows it once.  The stub below answers like #502's mPCC.
"""
import base64
import http.server
import io
import json
import os
import socket
import stat
import threading
from pathlib import Path

import pytest
import yaml

from mash.app import MprovShell, TimeoutSession

CA = str(Path(__file__).resolve().parent / "certs" / "ca.pem")
USAGE = "Usage: connect"


def basic(user, password):
  return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


class Handler(http.server.BaseHTTPRequestHandler):
  'An mPCC with /tokens/ (0.7), or without it (0.6) when server.tokens is False.'
  def log_message(self, *args):
    pass

  def _reply(self, code, body=None):
    data = json.dumps(body).encode() if body is not None else b""
    self.send_response(code)
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(data)))
    self.end_headers()
    self.wfile.write(data)

  def _record(self, body=None):
    self.server.seen.append((self.command, self.path, self.headers.get("Authorization"),
                             self.headers.get("mProv-Version"), body))

  def do_GET(self):
    self._record()
    if self.path == "/datamodel/":
      return self._reply(200, {"datamodels": ["systems"]})
    if self.path.startswith("/datamodel/?model="):
      return self._reply(200, {"endpoint": "/systems/", "fields": {}})
    if self.path == "/tokens/":
      if not self.server.tokens:
        return self._reply(404, {"detail": "Not found."})
      auth = self.headers.get("Authorization", "")
      if self.headers.get("mProv-Version") is None:
        return self._reply(426, {"detail": "Send the mProv-Version header."})
      if auth == "Token good":
        return self._reply(200, [])
      if auth == "Token revoked":
        return self._reply(401, {"detail": "This token was revoked."})
      if auth == "Token old":
        return self._reply(426, {"detail": "mash 0.6 doesn't match this mPCC's API version 0.7."})
      return self._reply(401, {"detail": "Unknown token."})
    return self._reply(200, {})

  def do_POST(self):
    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
    self._record(body)
    if self.path != "/tokens/" or not self.server.tokens:
      return self._reply(404, {"detail": "Not found."})
    auth = self.headers.get("Authorization")
    if auth == basic("alice", "pw"):
      return self._reply(201, {"token": "good", "name": body.get("name"), "prefix": "good"})
    if auth == basic("bob", "pw"):
      return self._reply(403, {"detail": "You do not have permission to perform this action."})
    return self._reply(401, {"detail": "Invalid username/password."})


def serve(tokens=True):
  server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
  server.daemon_threads = True
  server.seen = []
  server.tokens = tokens
  threading.Thread(target=server.serve_forever, daemon=True).start()
  server.url = f"http://127.0.0.1:{server.server_port}"
  return server


@pytest.fixture
def mpcc():
  server = serve()
  yield server
  server.shutdown()
  server.server_close()


@pytest.fixture
def old_mpcc():
  server = serve(tokens=False)
  yield server
  server.shutdown()
  server.server_close()


@pytest.fixture
def shell(tmp_path):
  s = MprovShell()
  # MprovShell.session is shared by every instance; give each test its own.
  s.session = TimeoutSession()
  # cmd.Cmd keeps the sys.stdout it was made with, before capsys swaps it
  s.stdout = io.StringIO()
  s.configfiles = [str(tmp_path / "missing.yaml")]
  s.tokenfile = str(tmp_path / "home" / ".mprov-mash.yaml")
  (tmp_path / "home").mkdir()
  return s


def tokens_calls(server):
  return [entry for entry in server.seen if entry[1] == "/tokens/"]


# connecting with a token

def test_token_connects_and_is_checked(shell, mpcc, capsys):
  shell.onecmd(f"connect {mpcc.url}/ token good")
  assert not shell.failed, capsys.readouterr().err
  assert "systems" in shell.models
  assert tokens_calls(mpcc) == [("GET", "/tokens/", "Token good", shell.mashVersion, None)]
  assert capsys.readouterr().err == ""


def test_token_from_the_config(shell, mpcc, tmp_path):
  conf = tmp_path / "mash.yaml"
  conf.write_text(f"global:\n  mprovURL: {mpcc.url}/\n  token: good\n")
  shell.configfiles = [str(conf)]
  shell.onecmd("connect")
  assert not shell.failed
  assert tokens_calls(mpcc)[0][2] == "Token good"


@pytest.mark.parametrize("token, reason", [
  ("revoked", "code: 401: This token was revoked."),
  ("nonsense", "code: 401: Unknown token."),
  ("old", "code: 426: mash 0.6 doesn't match"),
])
def test_refused_token_fails_connect_with_the_reason(shell, mpcc, capsys, token, reason):
  shell.onecmd(f"connect {mpcc.url} token {token}")
  err = capsys.readouterr().err
  assert shell.failed
  assert "refused the token" in err and reason in err
  assert shell.models == {}
  assert not any(entry[1] == "/datamodel/" for entry in mpcc.seen)


def test_token_on_an_mpcc_without_tokens(shell, old_mpcc, capsys):
  shell.onecmd(f"connect {old_mpcc.url} token good")
  assert shell.failed
  assert "need mPCC 0.7 or later" in capsys.readouterr().err


def test_apikey_is_not_checked_against_tokens(shell, mpcc, capsys):
  shell.onecmd(f"connect {mpcc.url} apikey k")
  assert not shell.failed
  assert tokens_calls(mpcc) == []
  assert "shared API key is being replaced by per-user tokens" in capsys.readouterr().err


@pytest.mark.parametrize("args", [
  "http://mpcc/ token",
  "http://mpcc/ token a b",
  "http://mpcc/ user alice save-token one two",
  "http://mpcc/ user save-token",
  "http://mpcc/ apikey k save-token",
  "http://mpcc/ token t save-token",
])
def test_malformed_token_commands_print_usage(shell, args, capsys):
  shell.onecmd(f"connect {args}")
  assert shell.failed
  assert USAGE in capsys.readouterr().err


# save-token

def test_save_token_writes_a_new_config(shell, mpcc, capsys):
  shell.onecmd(f"connect {mpcc.url}/ user alice password pw save-token laptop")
  out = shell.stdout.getvalue()
  assert not shell.failed
  post = [entry for entry in mpcc.seen if entry[0] == "POST"]
  assert post == [("POST", "/tokens/", basic("alice", "pw"), shell.mashVersion, {"name": "laptop"})]
  path = Path(shell.tokenfile)
  assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
  assert yaml.safe_load(path.read_text()) == {"global": {"mprovURL": mpcc.url, "token": "good"}}
  assert f"saved it to {path}" in out
  assert "good" not in out
  # then it connected with the new token, not the password
  assert tokens_calls(mpcc)[-1][:3] == ("GET", "/tokens/", "Token good")
  assert shell.session.headers["Authorization"] == "Token good"


def test_save_token_default_name_and_ca(shell, mpcc):
  shell.onecmd(f"connect {mpcc.url} user alice password pw save-token ca {CA}")
  post = [entry for entry in mpcc.seen if entry[0] == "POST"]
  assert post[0][4] == {"name": f"mash@{socket.gethostname()}"}
  assert yaml.safe_load(Path(shell.tokenfile).read_text())["global"]["caBundle"] == CA


def test_save_token_prompts_for_the_password(shell, mpcc, monkeypatch):
  monkeypatch.setattr("sys.stdin.isatty", lambda: True)
  monkeypatch.setattr("getpass.getpass", lambda prompt: "pw")
  shell.onecmd(f"connect {mpcc.url} user alice save-token")
  assert not shell.failed
  assert Path(shell.tokenfile).exists()


def test_save_token_never_overwrites_a_config(shell, mpcc, capsys):
  path = Path(shell.tokenfile)
  path.write_text("global:\n  mprovURL: http://elsewhere/\n  apikey: k\n")
  shell.onecmd(f"connect {mpcc.url} user alice password pw save-token")
  out = shell.stdout.getvalue()
  assert not shell.failed
  assert path.read_text() == "global:\n  mprovURL: http://elsewhere/\n  apikey: k\n"
  assert "shown only this once" in out and "already exists" in out
  assert "  good\n" in out


def test_save_token_shows_it_when_the_file_cant_be_written(shell, mpcc, tmp_path, capsys):
  shell.tokenfile = str(tmp_path / "no-such-dir" / ".mprov-mash.yaml")
  shell.onecmd(f"connect {mpcc.url} user alice password pw save-token")
  out = shell.stdout.getvalue()
  assert not shell.failed
  assert "can't be written" in out and "  good\n" in out


@pytest.mark.parametrize("user, reason", [
  ("bob", "code: 403: You do not have permission"),
  ("eve", "code: 401: Invalid username/password."),
])
def test_save_token_refused(shell, mpcc, capsys, user, reason):
  shell.onecmd(f"connect {mpcc.url} user {user} password pw save-token")
  err = capsys.readouterr().err
  assert shell.failed
  assert "didn't make a token" in err and reason in err
  assert not Path(shell.tokenfile).exists()
  assert tokens_calls(mpcc) == [entry for entry in mpcc.seen if entry[0] == "POST"]


def test_save_token_on_an_mpcc_without_tokens(shell, old_mpcc, capsys):
  shell.onecmd(f"connect {old_mpcc.url} user alice password pw save-token")
  assert shell.failed
  assert "need mPCC 0.7 or later" in capsys.readouterr().err
  assert not Path(shell.tokenfile).exists()
