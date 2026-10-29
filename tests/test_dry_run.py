"""Dry-run mode (mprov-ng/mash#43).

'dryrun on' (or 'mash --dry-run') makes create/update/delete and the
'bmc power' actions other than status print the request they would send
instead of sending it, and sets MPROV_RESULT to None.  retrieve still
goes out, so a foreach over its result can be previewed.  With 'output
json' each held-back request is one JSON object.
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

SYSTEMS = [{"id": 10, "hostname": "node01"}, {"id": 11, "hostname": "node02"}]
MODEL = {"endpoint": "/systems/", "fields": {"id": {"required": False}, "hostname": {"required": True}}}


def make_handler(seen):
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

    def do_GET(self):
      if self.path == "/datamodel/":
        return self._reply(200, {"datamodels": ["systems"]})
      if self.path.startswith("/datamodel/?model="):
        return self._reply(200, MODEL)
      if self.path != "/":  # connect's check
        seen.append(("GET", self.path))
      if self.path.startswith("/systems/"):
        return self._reply(200, SYSTEMS)
      if self.path.startswith("/power/"):
        return self._reply(200, {"node01-bmc": {"status": 200, "details": "on"}})
      return self._reply(200, {})

    def do_POST(self):
      seen.append(("POST", self.path))
      return self._reply(201, {"id": 12})

    def do_PATCH(self):
      seen.append(("PATCH", self.path))
      return self._reply(200, SYSTEMS[0])

    def do_DELETE(self):
      seen.append(("DELETE", self.path))
      return self._reply(204)
  return Handler


@pytest.fixture
def mpcc(tmp_path):
  seen = []
  server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(seen))
  server.daemon_threads = True
  threading.Thread(target=server.serve_forever, daemon=True).start()
  url = f"http://127.0.0.1:{server.server_port}"
  (tmp_path / ".mprov-mash.yaml").write_text(f"global:\n  mprovURL: {url}/\n  apikey: k\n")
  yield tmp_path, url, seen
  server.shutdown()
  server.server_close()


def mash(script, home, *args):
  e = dict(os.environ)
  e["PYTHONPATH"] = str(SRC) + os.pathsep + e.get("PYTHONPATH", "")
  e["HOME"] = str(home)
  return subprocess.run([sys.executable, "-m", "mash.main"] + list(args), input=script,
                        capture_output=True, text=True, env=e, timeout=30)


def test_changes_are_shown_not_sent(mpcc):
  home, url, seen = mpcc
  r = mash("connect\ndryrun on\n"
           "create systems hostname=node03\n"
           "update systems id=10 hostname=node04\n"
           "delete systems id=10 hostname=node01\n"
           "pvar MPROV_RESULT\n", home)
  assert (r.returncode, r.stderr) == (0, "")
  assert r.stdout.splitlines() == [
    f'DRY RUN: POST {url}/systems/ {{"hostname": "node03"}}',
    f'DRY RUN: PATCH {url}/systems/10/ {{"id": "10", "hostname": "node04"}}',
    f"DRY RUN: DELETE {url}/systems/10/?id=10&hostname=node01",
    "MPROV_RESULT=None",
  ]
  assert seen == []


def test_retrieve_still_goes_out_so_foreach_can_be_previewed(mpcc):
  home, url, seen = mpcc
  r = mash("connect\ndryrun on\n"
           "retrieve systems\n"
           "foreach sys in MPROV_RESULT\n"
           "delete systems id={{ sys.id }}\n"
           "endforeach\n", home)
  assert (r.returncode, r.stderr) == (0, "")
  assert r.stdout.splitlines() == [
    f"DRY RUN: DELETE {url}/systems/10/?id=10",
    f"DRY RUN: DELETE {url}/systems/11/?id=11",
  ]
  assert seen == [("GET", "/systems/")]


def test_dryrun_off_sends_again(mpcc):
  home, url, seen = mpcc
  r = mash("connect\ndryrun\ndryrun on\ndryrun\ndelete systems id=10\n"
           "dryrun off\ndryrun\ndelete systems id=11\n", home)
  assert (r.returncode, r.stderr) == (0, "")
  assert r.stdout.splitlines() == [
    "off", "on", f"DRY RUN: DELETE {url}/systems/10/?id=10", "off"]
  assert seen == [("DELETE", "/systems/11/?id=11")]


def test_dry_run_flag_and_json_output(mpcc):
  home, url, seen = mpcc
  r = mash("connect\nupdate systems id=10 hostname=node04\ndelete systems id=10\n",
           home, "--dry-run", "--json")
  assert (r.returncode, r.stderr) == (0, "")
  assert [json.loads(l) for l in r.stdout.splitlines()] == [
    {"dry_run": True, "method": "PATCH", "url": f"{url}/systems/10/",
     "data": {"id": "10", "hostname": "node04"}},
    {"dry_run": True, "method": "DELETE", "url": f"{url}/systems/10/?id=10", "data": None},
  ]
  assert seen == []


def test_bad_arguments_are_still_errors(mpcc):
  home, url, seen = mpcc
  r = mash("connect\ndryrun on\ncreate systems\nupdate systems bogus=1\ndryrun maybe\n", home)
  assert r.returncode == 1
  assert "Missing field required hostname" in r.stderr
  assert "does not have field bogus" in r.stderr
  assert "Usage: dryrun [on|off]" in r.stderr
  assert r.stdout == ""
  assert seen == []


def test_background_command_is_shown_not_sent(mpcc):
  home, url, seen = mpcc
  r = mash("connect\ndryrun on\ndelete systems id=10 &\n", home)
  assert (r.returncode, r.stderr) == (0, "")
  assert r.stdout.splitlines() == [f"DRY RUN: DELETE {url}/systems/10/?id=10"]
  assert seen == []


def test_bmc_power_actions_are_held_back_but_status_runs(mpcc):
  home, url, seen = mpcc
  r = mash("connect\ndryrun on\nbmc power cycle node0[1-2]\nbmc power status node01\n", home)
  assert (r.returncode, r.stderr) == (0, "")
  assert r.stdout.splitlines() == [
    f"node01: DRY RUN GET {url}/power/cycle/?hostname=node01",
    f"node02: DRY RUN GET {url}/power/cycle/?hostname=node02",
    "node01: on",
  ]
  assert seen == [("GET", "/power/status/?hostname=node01")]
