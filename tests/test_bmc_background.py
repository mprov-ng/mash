"""'bmc ... &' runs in the background, and bmc power checks its action (mprov-ng/mash#37, #41).

Before, the plugin's '&' handling was in a precmd() that never ran, so
'bmc power on node01 &' asked the mPCC for the host 'node01 ' and got a
404.  A trailing '&' on any plugin command now forks like the CRUD verbs.
The power help lists every action the mPCC carries out (status, pxe and
pxeefi were missing), and an unknown action is refused before anything
is sent, since the mPCC answers 200 to any action and does nothing.
"""
import http.server
import json
import os
import subprocess
import sys
import threading
from io import StringIO
from pathlib import Path

import pytest

from mash.app import MprovShell

SRC = Path(__file__).resolve().parent.parent / "src"


class Handler(http.server.BaseHTTPRequestHandler):
  'Answers the connect probe and /datamodel/; powers any host but "bad".'
  def log_message(self, *args):
    pass

  def do_GET(self):
    self.server.paths.append(self.path)
    code, body = 200, {}
    if self.path == "/datamodel/":
      body = {"datamodels": []}
    elif self.path.startswith("/power/"):
      host = self.path.split("hostname=", 1)[-1]
      if host == "bad":
        code, body = 500, "power daemon down"
      else:
        body = {f"{host}-bmc": None}
    data = (body if isinstance(body, str) else json.dumps(body)).encode()
    self.send_response(code)
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(data)))
    self.end_headers()
    self.wfile.write(data)


@pytest.fixture
def mpcc(tmp_path):
  server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
  server.daemon_threads = True
  server.paths = []
  threading.Thread(target=server.serve_forever, daemon=True).start()
  (tmp_path / ".mprov-mash.yaml").write_text(
    f"global:\n  mprovURL: http://127.0.0.1:{server.server_port}/\n  apikey: abc\n")
  server.home = tmp_path
  yield server
  server.shutdown()
  server.server_close()


def mash(script, home):
  e = dict(os.environ)
  e["PYTHONPATH"] = str(SRC) + os.pathsep + e.get("PYTHONPATH", "")
  e["HOME"] = str(home)
  return subprocess.run(
    [sys.executable, "-m", "mash.main"], input=script,
    capture_output=True, text=True, env=e, timeout=30,
  )


def power_paths(server):
  return sorted(p for p in server.paths if p.startswith("/power/"))


def test_backgrounded_bmc_power_runs(mpcc):
  r = mash("connect\nbmc power on node01 &\nbmc power off node02 &\nprint after\n", mpcc.home)
  assert r.returncode == 0, r.stderr
  assert power_paths(mpcc) == ["/power/off/?hostname=node02", "/power/on/?hostname=node01"]
  assert "node01: OK" in r.stdout
  assert "node02: OK" in r.stdout
  assert r.stdout.count("after") == 1


def test_failed_background_bmc_fails_the_script(mpcc):
  r = mash("connect\nbmc power on bad &\nprint after\n", mpcc.home)
  assert r.returncode == 1
  assert "failed on one or more nodes" in r.stderr
  assert r.stdout.count("after") == 1


@pytest.fixture
def shell():
  class NoNetwork:
    def get(self, *args, **kwargs):
      raise AssertionError("no request should be sent")
  s = MprovShell()
  s.stdout = StringIO()
  s.mprovURL = "http://mpcc"
  s.session = NoNetwork()
  return s


def test_unknown_power_action_is_refused(shell, capsys):
  shell.onecmd("bmc power reboot node01")
  assert "unknown power action 'reboot'" in capsys.readouterr().err
  assert shell.failed


def test_power_help_lists_every_action(shell):
  shell.onecmd("bmc power")
  help_text = shell.stdout.getvalue()
  for action in ["on", "off", "cycle", "reset", "status", "pxe", "pxeefi"]:
    assert action in help_text
  assert "node range" in help_text
