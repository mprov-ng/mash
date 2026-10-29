"""Dependency bounds (mprov-ng/mash#45).

Every runtime dependency has a lower and an upper bound, and the lower
bounds are the versions CI's "minimum" job pins in tests/min-versions.txt,
so the oldest versions mash claims to support are the ones it is tested on.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def entries(path):
  'name -> specifier for each requirement line, comments dropped.'
  out = {}
  for line in path.read_text().splitlines():
    line = line.split("#", 1)[0].strip()
    if line:
      name, spec = re.match(r"([A-Za-z0-9_.-]+)\s*(.*)", line).groups()
      out[name.lower()] = spec.replace(" ", "")
  return out


def test_every_dependency_is_bounded():
  for name, spec in entries(ROOT / "requirements.txt").items():
    assert re.fullmatch(r">=[\d.]+,<[\d.]+", spec), f"{name}: {spec!r}"


def test_lower_bounds_match_the_minimum_pins():
  pins = entries(ROOT / "tests" / "min-versions.txt")
  for name, spec in entries(ROOT / "requirements.txt").items():
    assert pins.get(name) == "==" + spec.split(",")[0][2:], name
