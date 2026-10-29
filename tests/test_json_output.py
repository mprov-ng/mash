"""JSON output mode (mprov-ng/mash#42).

'output json' (or 'mash --json') makes each command print its result as
one line of compact JSON on stdout: the mPCC's reply for the CRUD verbs
(null when it has none, e.g. a 204 delete), a list for 'models', an
object for 'model' and 'pvar'.  Errors stay on stderr, so stdout can go
straight to jq.  'output text' goes back to the default.
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
WRAPPER = SRC / "mash" / "mash"

SYSTEM = {"id": 10, "hostname": "node01"}
MODEL = {"endpoint": "/systems/", "fields": {"id": {"required": False}, "hostname": {"required": True}}}


class Handler(http.server.BaseHTTPRequestHandler):
  def log_message(self, *args):
    pass

  def _reply(self, code, body=None):
    data = b"" if body is None else json.dumps(body).encode()
    self.send_response(code)
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(data)))
    self.end_headers()
    self.wfile.write(data)

  def _body(self):
    return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

  def do_GET(self):
    if self.path == "/datamodel/":
      return self._reply(200, {"datamodels": ["systems"]})
    if self.path.startswith("/datamodel/?model="):
      return self._reply(200, MODEL)
    if self.path.startswith("/systems/"):
      return self._reply(200, [SYSTEM])
    return self._reply(200, {})

  def do_POST(self):
    return self._reply(201, {"id": 11, **self._body()})

  def do_PATCH(self):
    return self._reply(200, {**SYSTEM, **self._body()})

  def do_DELETE(self):
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


def mash(script, home, *args, cmd=None):
  e = dict(os.environ)
  e["PYTHONPATH"] = str(SRC) + os.pathsep + e.get("PYTHONPATH", "")
  e["HOME"] = str(home)
  return subprocess.run((cmd or [sys.executable, "-m", "mash.main"]) + list(args), input=script,
                        capture_output=True, text=True, env=e, timeout=30)


def lines(r):
  return [json.loads(line) for line in r.stdout.splitlines()]


def test_crud_replies_as_json_lines(home):
  r = mash("connect\noutput json\n"
           "retrieve systems hostname=node01\n"
           "create systems hostname=node02\n"
           "update systems id=10 hostname=node03\n"
           "delete systems id=10\n", home)
  assert (r.returncode, r.stderr) == (0, "")
  assert lines(r) == [
    [SYSTEM],
    {"id": 11, "hostname": "node02"},
    {"id": "10", "hostname": "node03"},
    None,
  ]
  # compact: one line each, no spaces after separators
  assert r.stdout.splitlines()[0] == '[{"id":10,"hostname":"node01"}]'


def test_json_flag_starts_in_json_mode(home):
  r = mash("connect\nretrieve systems\n", home, "--json")
  assert (r.returncode, lines(r)) == (0, [[SYSTEM]])


def test_json_flag_with_a_script_file_through_the_wrapper(home):
  script = home / "get.mash"
  script.write_text("connect\nretrieve systems\n")
  r = mash(None, home, "--json", str(script), cmd=["bash", str(WRAPPER)])
  assert (r.returncode, lines(r)) == (0, [[SYSTEM]])


def test_errors_stay_off_stdout(home):
  r = mash("connect\nretrieve bogusmodel\nretrieve systems\n", home, "--json")
  assert r.returncode == 1
  assert "Unknown Model bogusmodel" in r.stderr
  assert lines(r) == [[SYSTEM]]


def test_models_model_and_pvar(home):
  r = mash("connect\nlet a=1\nlet b=two\noutput json\nmodels\nmodel systems\npvar a\npvar a, b\n", home)
  assert (r.returncode, r.stderr) == (0, "")
  assert lines(r) == [["systems"], MODEL, {"a": "1"}, {"a": "1", "b": "two"}]


def test_backgrounded_commands_print_their_replies(home):
  r = mash("connect\noutput json\nretrieve systems &\ndelete systems id=10 &\n", home)
  assert r.returncode == 0, r.stderr
  assert sorted(lines(r), key=json.dumps) == sorted([[SYSTEM], None], key=json.dumps)


def test_output_text_goes_back_and_output_shows_the_mode(home):
  r = mash("output\noutput json\noutput\noutput text\nconnect\nretrieve systems\npvar MPROV_RESULT\n", home)
  assert r.returncode == 0, r.stderr
  assert r.stdout.splitlines() == ["text", "json", "MPROV_RESULT=[{'id': 10, 'hostname': 'node01'}]"]


def test_bad_output_mode(home):
  r = mash("output yaml\n", home)
  assert r.returncode == 1
  assert "Usage: output [json|text]" in r.stderr


def test_backtick_capture_gets_the_json(home):
  r = mash("connect\noutput json\nlet j=`retrieve systems\noutput text\nprint {{ j }}\n", home)
  assert r.returncode == 0, r.stderr
  assert json.loads(r.stdout) == [SYSTEM]
