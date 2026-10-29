"""A hung mPCC can't wedge the shell (mprov-ng/mash#29, #30).

Every request has a timeout (and a timed-out reply isn't retried), and
SIGINT/SIGTERM aren't ignored any more: Ctrl-C at the interactive prompt
stops the command and goes back to the prompt, in a script it stops the
script.
"""
import http.server
import json
import os
import pty
import select
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from mash.app import DEFAULT_TIMEOUT, TimeoutSession

SRC = Path(__file__).resolve().parent.parent / "src"


class FakeMPCC(http.server.ThreadingHTTPServer):
  'Answers / and /datamodel/, never replies to /systems/.'
  daemon_threads = True

  def __init__(self):
    self.hung = []
    self.release = threading.Event()
    super().__init__(("127.0.0.1", 0), Handler)


class Handler(http.server.BaseHTTPRequestHandler):
  def log_message(self, *args):
    pass

  def do_GET(self):
    if self.path.startswith("/systems/"):
      self.server.hung.append(self.path)
      self.server.release.wait(60)
      return
    if self.path == "/datamodel/":
      body = {"datamodels": ["systems"]}
    elif self.path.startswith("/datamodel/?model="):
      body = {"endpoint": "/systems/"}
    else:
      body = {}
    data = json.dumps(body).encode()
    self.send_response(200)
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(data)))
    self.end_headers()
    self.wfile.write(data)


@pytest.fixture
def mpcc():
  server = FakeMPCC()
  threading.Thread(target=server.serve_forever, daemon=True).start()
  yield server
  server.release.set()
  server.shutdown()
  server.server_close()


def env(home):
  e = dict(os.environ)
  e["PYTHONPATH"] = str(SRC) + os.pathsep + e.get("PYTHONPATH", "")
  e["HOME"] = str(home)
  return e


@pytest.fixture
def home(tmp_path, mpcc):
  def write(timeout=None):
    lines = ["global:", f"  mprovURL: http://127.0.0.1:{mpcc.server_port}/", "  apikey: abc"]
    if timeout is not None:
      lines.append(f"  timeout: {timeout}")
    (tmp_path / ".mprov-mash.yaml").write_text("\n".join(lines) + "\n")
    return tmp_path
  return write


def wait_for(cond, seconds=10):
  end = time.monotonic() + seconds
  while time.monotonic() < end:
    if cond():
      return True
    time.sleep(0.05)
  return False


def test_session_has_a_default_timeout(monkeypatch):
  seen = {}
  def fake_request(self, method, url, **kwargs):
    seen.update(kwargs)
  monkeypatch.setattr("requests.Session.request", fake_request)
  s = TimeoutSession()
  s.get("http://mpcc/")
  assert seen["timeout"] == DEFAULT_TIMEOUT
  s.get("http://mpcc/", timeout=None)
  assert seen["timeout"] == DEFAULT_TIMEOUT
  s.get("http://mpcc/", timeout=5)
  assert seen["timeout"] == 5


def test_hung_request_times_out_once_and_the_script_goes_on(home, mpcc):
  start = time.monotonic()
  r = subprocess.run(
    [sys.executable, "-m", "mash.main"],
    input="connect\nretrieve systems\nprint after\n",
    capture_output=True, text=True, env=env(home(timeout=1)), timeout=30,
  )
  assert time.monotonic() - start < 10
  assert "Read timed out" in r.stderr
  assert r.returncode == 1
  assert r.stdout.rstrip().endswith("after")
  # a reply that timed out isn't retried
  assert len(mpcc.hung) == 1


def test_bad_timeout_in_the_config(home):
  r = subprocess.run(
    [sys.executable, "-m", "mash.main"], input="connect\n",
    capture_output=True, text=True, env=env(home(timeout="soon")), timeout=30,
  )
  assert "'timeout' must be a number of seconds greater than 0" in r.stderr


@pytest.mark.parametrize("sig, code", [(signal.SIGINT, 130), (signal.SIGTERM, -signal.SIGTERM)])
def test_signal_stops_a_script_stuck_on_a_request(home, mpcc, sig, code):
  script = home() / "hang.mash"
  script.write_text("connect\nretrieve systems\nprint after\n")
  p = subprocess.Popen(
    [sys.executable, "-m", "mash.main", str(script)], stdin=subprocess.DEVNULL,
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env(script.parent),
  )
  try:
    assert wait_for(lambda: mpcc.hung)
    p.send_signal(sig)
    out, err = p.communicate(timeout=10)
  finally:
    p.kill()
  assert p.returncode == code
  assert "after" not in out
  assert "Traceback" not in err


def read_until(fd, text, seconds=10):
  buf = b""
  end = time.monotonic() + seconds
  while text.encode() not in buf:
    left = end - time.monotonic()
    if left <= 0:
      raise AssertionError(f"never saw {text!r} in {buf!r}")
    if select.select([fd], [], [], left)[0]:
      buf += os.read(fd, 4096)
  return buf.decode()


def test_ctrl_c_at_the_prompt_stops_the_command_not_the_shell(home, mpcc):
  leader, follower = pty.openpty()
  p = subprocess.Popen(
    [sys.executable, "-m", "mash.main"],
    stdin=follower, stdout=follower, stderr=follower, env=env(home()),
  )
  os.close(follower)
  try:
    read_until(leader, "<mProv> # ")
    os.write(leader, b"connect\n")
    read_until(leader, "<mProv> # ")
    os.write(leader, b"retrieve systems\n")
    assert wait_for(lambda: mpcc.hung)
    p.send_signal(signal.SIGINT)
    read_until(leader, "^C")
    os.write(leader, b"print still-here\n")
    assert "still-here" in read_until(leader, "still-here")
    assert p.poll() is None
    os.write(leader, b"exit\n")
    assert p.wait(timeout=10) == 0
  finally:
    p.kill()
    os.close(leader)
