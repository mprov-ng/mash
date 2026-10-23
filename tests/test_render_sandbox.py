"""Script text renders in a sandboxed Jinja2 environment (mprov-ng/mash#18).

A .mash script's template text must not walk Python attributes
(``__class__``/``__mro__``/``__globals__``) into executable internals with
the invoking user's permissions.  A denied payload must degrade to the raw
template string, and ordinary variable interpolation must keep working.
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
  sys.path.insert(0, str(SRC))

from mash.app import MprovShell


def render(tempStr, variables=None):
  shell = MprovShell()
  shell.variables = dict(variables or {})
  return shell.renderString(tempStr)


def test_plain_interpolation_still_works():
  assert render("hello {{ name }}", {"name": "world"}) == "hello world"


def test_mro_subclasses_payload_is_blocked():
  out = render("{{ ''.__class__.__mro__[1].__subclasses__()|length }}")
  assert not out.strip().isdigit()


def test_globals_payload_is_blocked():
  out = render("{{ fn.__globals__ }}", {"fn": render})
  assert "__builtins__" not in out
