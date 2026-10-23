"""A failed API call must not leave a stale MPROV_RESULT (mprov-ng/mash#26).

Before the fix, _sendHttpRequest returned early on most error paths without
clearing MPROV_RESULT, so the command after a failure still saw the previous
command's result through 'pvar MPROV_RESULT' / jinja templating.
"""
from io import StringIO

import pytest

from mash.app import MprovShell

STALE = ["stale-result-from-the-previous-command"]


class FakeResponse:
  def __init__(self, status_code=200, payload=None, bad_json=False):
    self.status_code = status_code
    self._payload = payload
    self._bad_json = bad_json
    self.text = "server says no"

  def json(self):
    if self._bad_json:
      raise ValueError("no json here")
    return self._payload


class FakeSession:
  'Every verb answers with the canned response.'
  def __init__(self, response):
    self.response = response

  def get(self, *args, **kwargs):
    return self.response

  def post(self, *args, **kwargs):
    return self.response

  def patch(self, *args, **kwargs):
    return self.response

  def delete(self, *args, **kwargs):
    return self.response


@pytest.fixture
def shell():
  s = MprovShell()
  s.stdout = StringIO()            # keep error prints out of the test log
  s.variables = {"MPROV_RESULT": STALE}   # instance dict; the class one is shared
  s.models = {
    "thing": {"endpoint": "/thing/", "fields": {"name": {"required": True}}},
    "noep": {"fields": {}},        # model without a registered endpoint
  }
  s.session = FakeSession(FakeResponse(status_code=500))
  return s


@pytest.mark.parametrize("name,call", [
  ("no argument", lambda s: s._sendHttpRequest("get", "")),
  ("unknown model", lambda s: s._sendHttpRequest("get", "nope id=1")),
  ("model without endpoint", lambda s: s._sendHttpRequest("get", "noep")),
  ("unknown field", lambda s: s._sendHttpRequest("post", "thing bogus=1")),
  ("missing required field", lambda s: s._sendHttpRequest("post", "thing", checkargs=True)),
  ("unsupported method", lambda s: s._sendHttpRequest("put", "thing")),
  ("communications error (http 500)", lambda s: s._sendHttpRequest("get", "thing")),
  ("unparseable success body", lambda s: _get_bad_json(s)),
])
def test_error_paths_clear_stale_result(shell, name, call):
  call(shell)
  assert shell.variables["MPROV_RESULT"] is None, \
     f"{name}: stale MPROV_RESULT survived a failed command"


def _get_bad_json(s):
  s.session.response = FakeResponse(status_code=200, bad_json=True)
  s._sendHttpRequest("get", "thing id=1")


def test_failed_call_clears_stale_result(shell):
  'The filed symptom: retrieve succeeds, then delete answers 500 — no stale list may remain.'
  shell.session.response = FakeResponse(status_code=200, payload=STALE)
  shell._sendHttpRequest("get", "thing")
  assert shell.variables["MPROV_RESULT"] == STALE   # precondition: result was set
  shell.session.response = FakeResponse(status_code=500)
  shell._sendHttpRequest("delete", "thing id=1")
  assert shell.variables["MPROV_RESULT"] is None


def test_successful_call_still_sets_result(shell):
  'Guards against over-clearing: the success path must still publish the response.'
  shell.session.response = FakeResponse(status_code=200, payload={"id": 7})
  shell._sendHttpRequest("get", "thing id=7")
  assert shell.variables["MPROV_RESULT"] == {"id": 7}
