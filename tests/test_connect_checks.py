"""connect reports a refused login, and checks the config's keys (mprov-ng/mash#38, #44).

Before, a non-200 answer to connect (a wrong API key or password: the
mPCC's / needs a login) printed nothing and loaded no models, and a
typo'd config key ('apiKey', 'mprovurl') connected with an empty
Authorization header.  Now connect reports the status, a missing
mprovURL or apikey stops it, and an unknown key in mash's own config
gets a warning.  The job server's jobserver.yaml, which mash falls back
to, has keys of its own, so it isn't checked for unknown keys.
"""
import http.server
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from mash.app import MprovShell

SRC = Path(__file__).resolve().parent.parent / "src"


class Refusing(http.server.BaseHTTPRequestHandler):
  def log_message(self, *args):
    pass

  def do_GET(self):
    data = b'{"detail":"Authentication credentials were not provided."}'
    self.send_response(403)
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(data)))
    self.end_headers()
    self.wfile.write(data)


def test_refused_connect_is_reported_and_fails_the_script(tmp_path):
  server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Refusing)
  server.daemon_threads = True
  threading.Thread(target=server.serve_forever, daemon=True).start()
  try:
    (tmp_path / ".mprov-mash.yaml").write_text(
      f"global:\n  mprovURL: http://127.0.0.1:{server.server_port}/\n  apikey: wrong\n")
    e = dict(os.environ)
    e["PYTHONPATH"] = str(SRC) + os.pathsep + e.get("PYTHONPATH", "")
    e["HOME"] = str(tmp_path)
    r = subprocess.run([sys.executable, "-m", "mash.main"], input="connect\n",
                       capture_output=True, text=True, env=e, timeout=30)
  finally:
    server.shutdown()
    server.server_close()
  assert r.returncode == 1
  assert "Unable to connect to mPCC" in r.stderr
  assert "code: 403; check the API key or user and password" in r.stderr
  assert "Authentication credentials were not provided." in r.stderr
  assert r.stdout == ""


@pytest.fixture
def connect(tmp_path, monkeypatch, capsys):
  'Write a config file, run a bare connect, return (headers sent, stderr, shell).'
  def run(text, name="mash.yaml"):
    cfg = tmp_path / name
    cfg.write_text(text)
    s = MprovShell()
    s.configfiles = [str(cfg)]
    s.mprovURL = ""
    sent = []
    monkeypatch.setattr(s, "_connectToMPCC", lambda header: sent.append(header))
    s.onecmd("connect")
    return sent, capsys.readouterr().err, s
  return run


def test_good_config_connects_quietly(connect):
  sent, err, s = connect("global:\n  mprovURL: http://mpcc/\n  apikey: k\n  timeout: 30\n")
  assert sent == ["Api-Key k"]
  assert err == ""
  assert not s.failed


def test_typo_in_a_key_warns_and_the_missing_key_stops_connect(connect):
  sent, err, s = connect("global:\n  mprovURL: http://mpcc/\n  apiKey: k\n")
  assert sent == []
  assert "unknown key 'apiKey' in 'global'; did you mean 'apikey'?" in err
  assert "'apikey' isn't set in 'global'" in err
  assert s.failed


@pytest.mark.parametrize("conf", [
  "global:\n  apikey: k\n",
  "global:\n  apikey: k\n  mprovURL: ''\n",
])
def test_missing_or_empty_url_stops_connect(connect, conf):
  sent, err, s = connect(conf)
  assert sent == []
  assert "'mprovURL' isn't set in 'global'" in err


def test_unknown_key_and_section_warn_but_connect(connect):
  sent, err, s = connect("global:\n  mprovURL: http://mpcc/\n  apikey: k\n  colour: blue\nextra:\n  a: 1\n")
  assert sent == ["Api-Key k"]
  assert "unknown key 'colour' in 'global'" in err
  assert "did you mean" not in err
  assert "unknown section 'extra'" in err
  assert not s.failed


def test_jobserver_yaml_keys_are_not_warned_about(connect):
  sent, err, s = connect(
    "- global:\n    mprovURL: http://mpcc/\n    apikey: k\n    heartbeatInterval: 10\n"
    "    myaddress: ''\n    jobmodules: []\n- dnsmasq:\n    x: 1\n",
    name="jobserver.yaml")
  assert sent == ["Api-Key k"]
  assert err == ""
