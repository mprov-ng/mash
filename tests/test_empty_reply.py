"""A successful reply with no body is a success (mprov-ng/mash#69).

The mPCC answers a successful delete with 204 and no body (DRF's
destroy()), and some views answer an empty 200.  mash tried to parse
that as JSON, reported "reply isn't JSON" and, since #66, failed the
script.  An empty 2xx now sets MPROV_RESULT to None and succeeds; a
body that isn't empty and isn't JSON is still an error.
"""
import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"


class Handler(http.server.BaseHTTPRequestHandler):
  def log_message(self, *args):
    pass

  def _reply(self, code, data=b""):
    self.send_response(code)
    self.send_header("Content-Length", str(len(data)))
    self.end_headers()
    self.wfile.write(data)

  def do_GET(self):
    if self.path == "/datamodel/":
      return self._reply(200, json.dumps({"datamodels": ["systems"]}).encode())
    if self.path.startswith("/datamodel/?model="):
      return self._reply(200, json.dumps({"endpoint": "/systems/", "fields": {"id": {}, "hostname": {}}}).encode())
    if self.path == "/systems/?hostname=empty":
      return self._reply(200)
    if self.path == "/systems/?hostname=html":
      return self._reply(200, b"<html>")
    return self._reply(200, b"{}")

  def do_DELETE(self):
    # what DRF's destroy() answers
    return self._reply(204)


@pytest.fixture
def home(tmp_path):
  server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
  server.daemon_threads = True
  threading.Thread(target=server.serve_forever, daemon=True).start()
  (tmp_path / ".mprov-mash.yaml").write_text(
    f"global:\n  mprovURL: http://127.0.0.1:{server.server_port}/\n  apikey: k\n")
  yield tmp_path
  server.shutdown()
  server.server_close()


def mash(script, home):
  e = dict(os.environ)
  e["PYTHONPATH"] = str(SRC) + os.pathsep + e.get("PYTHONPATH", "")
  e["HOME"] = str(home)
  return subprocess.run([sys.executable, "-m", "mash.main"], input=script,
                        capture_output=True, text=True, env=e, timeout=30)


def test_delete_answered_with_204_succeeds(home):
  r = mash("connect\nlet MPROV_RESULT=stale\ndelete systems id=5\npvar MPROV_RESULT\n", home)
  assert (r.returncode, r.stderr) == (0, "")
  assert r.stdout == "MPROV_RESULT=None\n"


def test_backgrounded_delete_answered_with_204_succeeds(home):
  r = mash("connect\ndelete systems id=5 &\ndelete systems id=6 &\n", home)
  assert (r.returncode, r.stderr) == (0, "")


def test_empty_200_succeeds(home):
  r = mash("connect\nretrieve systems hostname=empty\npvar MPROV_RESULT\n", home)
  assert (r.returncode, r.stderr) == (0, "")
  assert r.stdout == "MPROV_RESULT=None\n"


def test_body_that_isnt_json_is_still_an_error(home):
  r = mash("connect\nretrieve systems hostname=html\n", home)
  assert r.returncode == 1
  assert "reply isn't JSON" in r.stderr
