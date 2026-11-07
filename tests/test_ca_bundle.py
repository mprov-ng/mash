"""'connect ... ca <file>' and 'caBundle' verify an https mPCC (mprov-ng/mash#86).

Before, mash had no way to name a CA, and requests from PyPI trusts only
certifi, so an mPCC whose certificate is from a site or self-signed CA (as
every 0.7 mPCC's own per-install CA is, mprov_control_center#381) failed
to verify.  Now mash uses the CA file given, else the OS bundle, else
certifi, the same order as the job server (mprov_jobserver#102).

tests/certs holds a test-only CA's certificate (its key was thrown away)
and a server certificate for 127.0.0.1 it signed, valid until 2126.
"""
import http.server
import json
import ssl
import threading
from pathlib import Path

import pytest
import requests

from mash import app
from mash.app import MprovShell, TimeoutSession

CERTS = Path(__file__).resolve().parent / "certs"
CA = str(CERTS / "ca.pem")
USAGE = "Usage: connect"


class Handler(http.server.BaseHTTPRequestHandler):
  'Answers the connect probe and /datamodel/.'
  def log_message(self, *args):
    pass

  def do_GET(self):
    data = json.dumps({"datamodels": []} if self.path == "/datamodel/" else {}).encode()
    self.send_response(200)
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(data)))
    self.end_headers()
    self.wfile.write(data)


@pytest.fixture
def https_mpcc():
  server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
  server.daemon_threads = True
  context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
  context.load_cert_chain(str(CERTS / "server.pem"), str(CERTS / "server.key"))
  server.socket = context.wrap_socket(server.socket, server_side=True)
  threading.Thread(target=server.serve_forever, daemon=True).start()
  yield f"https://127.0.0.1:{server.server_port}"
  server.shutdown()
  server.server_close()


@pytest.fixture(autouse=True)
def no_ca_env(monkeypatch):
  'A REQUESTS_CA_BUNDLE in the environment the tests run in would change them.'
  monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
  monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)


@pytest.fixture
def no_os_bundle(monkeypatch):
  'As on a host with no OS CA bundle: requests falls back to certifi.'
  monkeypatch.setattr(app, "OS_CA_BUNDLES", ())


@pytest.fixture
def shell(monkeypatch, tmp_path):
  s = MprovShell()
  # MprovShell.session is shared by every instance; give each test its own.
  s.session = TimeoutSession()
  s.mprovURL = ""
  s.configfiles = [str(tmp_path / "missing.yaml")]
  s.connected = []
  monkeypatch.setattr(s, "_connectToMPCC", lambda header: s.connected.append(header))
  return s


def test_ca_after_apikey(shell):
  shell.onecmd(f"connect http://mpcc/ apikey abc123 ca {CA}")
  assert shell.connected == ["Api-Key abc123"]
  assert shell.mprovURL == "http://mpcc"
  assert shell.session.caBundle == CA


def test_ca_after_user_and_password(shell):
  shell.onecmd(f"connect http://mpcc/ user alice password s3cret ca {CA}")
  assert len(shell.connected) == 1
  assert shell.session.caBundle == CA


def test_missing_ca_file_is_an_error(shell, tmp_path, capsys):
  shell.onecmd(f"connect http://mpcc/ apikey abc123 ca {tmp_path / 'nope.pem'}")
  assert shell.connected == []
  assert "doesn't exist" in capsys.readouterr().err


@pytest.mark.parametrize("args", [
  f"http://mpcc/ ca {CA}",
  f"ca {CA}",
  "http://mpcc/ apikey abc123 ca",
])
def test_ca_without_a_login_prints_usage(shell, args, capsys):
  shell.onecmd(f"connect {args}")
  assert shell.connected == []
  assert USAGE in capsys.readouterr().err


def test_config_caBundle(shell, tmp_path):
  conf = tmp_path / "mash.yaml"
  conf.write_text(f"global:\n  mprovURL: http://mpcc/\n  apikey: abc\n  caBundle: {CA}\n")
  shell.configfiles = [str(conf)]
  shell.onecmd("connect")
  assert shell.connected == ["Api-Key abc"]
  assert shell.session.caBundle == CA


def test_config_caBundle_expands_home(shell, tmp_path, monkeypatch):
  monkeypatch.setenv("HOME", str(tmp_path))
  (tmp_path / "ca.pem").write_text(Path(CA).read_text())
  conf = tmp_path / "mash.yaml"
  conf.write_text("global:\n  mprovURL: http://mpcc/\n  apikey: abc\n  caBundle: ~/ca.pem\n")
  shell.configfiles = [str(conf)]
  shell.onecmd("connect")
  assert shell.session.caBundle == str(tmp_path / "ca.pem")


def test_config_caBundle_is_a_known_key(shell, tmp_path, capsys):
  conf = tmp_path / "mash.yaml"
  conf.write_text(f"global:\n  mprovURL: http://mpcc/\n  apikey: abc\n  caBundle: {CA}\n")
  shell.configfiles = [str(conf)]
  shell.onecmd("connect")
  assert "unknown key" not in capsys.readouterr().err


def test_defaults_to_the_os_bundle(shell, tmp_path, monkeypatch):
  bundle = tmp_path / "ca-bundle.crt"
  bundle.write_text("")
  monkeypatch.setattr(app, "OS_CA_BUNDLES", (str(tmp_path / "absent.crt"), str(bundle)))
  shell.onecmd("connect http://mpcc/ apikey abc123")
  assert shell.session.caBundle == str(bundle)


@pytest.mark.parametrize("var", ["REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"])
def test_ca_env_var_still_wins_over_the_os_bundle(shell, tmp_path, monkeypatch, var):
  bundle = tmp_path / "ca-bundle.crt"
  bundle.write_text("")
  monkeypatch.setattr(app, "OS_CA_BUNDLES", (str(bundle),))
  monkeypatch.setenv(var, CA)
  shell.onecmd("connect http://mpcc/ apikey abc123")
  assert shell.session.caBundle is None


def test_ca_arg_wins_over_the_env_var(shell, monkeypatch, tmp_path):
  monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(tmp_path / "other.pem"))
  shell.onecmd(f"connect http://mpcc/ apikey abc123 ca {CA}")
  assert shell.session.caBundle == CA


def test_no_os_bundle_leaves_requests_default(shell, no_os_bundle):
  shell.onecmd("connect http://mpcc/ apikey abc123")
  assert shell.session.caBundle is None


def test_a_new_connect_without_ca_drops_the_old_one(shell, no_os_bundle):
  shell.onecmd(f"connect http://mpcc/ apikey abc123 ca {CA}")
  shell.onecmd("connect http://other/ apikey abc123")
  assert shell.session.caBundle is None


def test_session_passes_its_ca_unless_the_caller_gives_verify(monkeypatch):
  seen = []
  monkeypatch.setattr(requests.Session, "request", lambda self, method, url, **kw: seen.append(kw.get("verify")))
  s = TimeoutSession()
  s.caBundle = CA
  s.get("https://mpcc/")
  s.get("https://mpcc/", verify=False)
  assert seen == [CA, False]


def real_shell():
  s = MprovShell()
  s.session = TimeoutSession()
  s.configfiles = []
  return s


def test_https_mpcc_verifies_with_its_ca(https_mpcc, no_os_bundle, capsys):
  s = real_shell()
  s.onecmd(f"connect {https_mpcc} apikey abc ca {CA}")
  assert not s.failed, capsys.readouterr().err
  assert s.models == {}


def test_https_mpcc_without_its_ca_points_at_ca(https_mpcc, no_os_bundle, capsys):
  s = real_shell()
  s.onecmd(f"connect {https_mpcc} apikey abc")
  err = capsys.readouterr().err
  assert s.failed
  assert "Unable to communicate" in err
  assert "'ca <file>'" in err and "caBundle" in err
