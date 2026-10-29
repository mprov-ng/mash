"""A backgrounded command's child process must exit when it's done.

Before, when a backgrounded ('... &') request failed (an unknown model, a
bad argument, an HTTP error), the forked child returned into the script
and ran the rest of it too, so every later command ran twice.
"""
import os
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"


def env():
  e = dict(os.environ)
  e["PYTHONPATH"] = str(SRC) + os.pathsep + e.get("PYTHONPATH", "")
  return e


def mash(input):
  return subprocess.run(
    [sys.executable, "-m", "mash.main"], input=input,
    capture_output=True, text=True, env=env(), timeout=30,
  )


def test_failed_background_request_does_not_rerun_the_script():
  r = mash("retrieve bogusmodel &\nprint after-1\nprint after-2\ndisconnect\n")
  assert r.returncode == 0
  assert "Error: Unknown Model bogusmodel." in r.stdout
  assert r.stdout.count("after-1") == 1
  assert r.stdout.count("after-2") == 1


def test_background_child_exits_after_a_rejected_argument():
  r = mash("create bogusmodel x &\nprint after\ndisconnect\n")
  assert r.stdout.count("after") == 1
