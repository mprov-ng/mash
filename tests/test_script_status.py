"""Errors go to stderr, and a script exits 1 if a command failed (mprov-ng/mash#31, #32).

Before, most error messages went to stdout, mixed in with the results a
script pipes on, and a script exited 0 however many of its commands
failed.  Now stdout carries only results, and a failed command (an
error on stderr, a failed background command) makes the script exit 1,
also through 'exit'.  Warnings don't change the exit status, and the
interactive shell still exits 0.
"""
import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from mash.app import MprovShell

SRC = Path(__file__).resolve().parent.parent / "src"


class Handler(http.server.BaseHTTPRequestHandler):
  'A tiny mPCC: model "systems"; /systems/?hostname=bad answers 500.'
  def log_message(self, *args):
    pass

  def _reply(self, code, body):
    data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    self.send_response(code)
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(data)))
    self.end_headers()
    self.wfile.write(data)

  def do_GET(self):
    if self.path == "/datamodel/":
      return self._reply(200, {"datamodels": ["systems"]})
    if self.path.startswith("/datamodel/?model="):
      return self._reply(200, {"endpoint": "/systems/", "fields": {"hostname": {"required": False}}})
    if self.path == "/systems/?hostname=bad":
      return self._reply(500, "server broke")
    if self.path == "/systems/?hostname=notjson":
      return self._reply(200, "<html>")
    return self._reply(200, [])

  do_DELETE = do_GET


@pytest.fixture
def home(tmp_path):
  server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
  server.daemon_threads = True
  threading.Thread(target=server.serve_forever, daemon=True).start()
  (tmp_path / ".mprov-mash.yaml").write_text(
    f"global:\n  mprovURL: http://127.0.0.1:{server.server_port}/\n  apikey: abc\n")
  yield tmp_path
  server.shutdown()
  server.server_close()


def mash(script, home=None):
  e = dict(os.environ)
  e["PYTHONPATH"] = str(SRC) + os.pathsep + e.get("PYTHONPATH", "")
  if home is not None:
    e["HOME"] = str(home)
  return subprocess.run(
    [sys.executable, "-m", "mash.main"], input=script,
    capture_output=True, text=True, env=e, timeout=30,
  )


def test_clean_script_exits_0():
  r = mash("let a=1\nprint {{ a }}\n")
  assert (r.returncode, r.stdout, r.stderr) == (0, "1\n", "")


def test_error_goes_to_stderr_and_the_script_exits_1():
  r = mash("retrieve bogusmodel\nprint after\n")
  assert r.returncode == 1
  assert r.stdout == "after\n"
  assert "Error: Unknown Model bogusmodel." in r.stderr


@pytest.mark.parametrize("verb", ["exit", "quit"])
def test_exit_after_a_failure_still_exits_1(verb):
  assert mash(f"pvar nosuchvar\n{verb}\nprint never\n").returncode == 1


def test_exit_in_a_clean_script_exits_0():
  r = mash("print hi\nexit\n")
  assert (r.returncode, r.stdout) == (0, "hi\n")


def test_http_error_and_body_go_to_stderr(home):
  r = mash("connect\nretrieve systems hostname=bad\nprint after\n", home)
  assert r.returncode == 1
  assert r.stdout == "after\n"
  assert "code: 500" in r.stderr
  assert "server broke" in r.stderr


def test_reply_that_isnt_json(home):
  r = mash("connect\nretrieve systems hostname=notjson\n", home)
  assert r.returncode == 1
  assert "reply isn't JSON" in r.stderr
  assert r.stdout == ""


def test_successful_requests_exit_0(home):
  r = mash("connect\nretrieve systems hostname=good\ndelete systems hostname=good &\n", home)
  assert r.returncode == 0, r.stderr
  assert (r.stdout, r.stderr) == ("", "")


def test_failed_background_command_fails_the_script_without_disconnect(home):
  r = mash("connect\ndelete systems hostname=bad &\nprint after\n", home)
  assert r.returncode == 1
  assert "code: 500" in r.stderr
  assert r.stdout.count("after") == 1


def test_unknown_key_warning_does_not_fail_the_script(home):
  r = mash("connect\nretrieve systems hostnme=good\n", home)
  assert r.returncode == 0
  assert "Warning: Model systems has no field hostnme" in r.stderr


def test_failed_bmc_power_fails_the_script():
  class Refused:
    def get(self, *args, **kwargs):
      raise OSError("connection refused")
  s = MprovShell()
  s.stdout = open(os.devnull, "w")
  s.mprovURL = "http://mpcc"
  s.session = Refused()
  s.onecmd("bmc power on node01")
  assert s.failed


def test_warn_does_not_set_failed():
  s = MprovShell()
  s.warn("just so you know")
  assert not s.failed
  s.err("this one counts")
  assert s.failed
