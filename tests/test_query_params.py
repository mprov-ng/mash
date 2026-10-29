"""retrieve/delete send the query that was typed (mprov-ng/mash#19, #36).

Each token must be key=value, and the values are URL-encoded, so a '&',
'#' or '%' in a value can't add, drop or change a filter.  A key that is
neither a field of the model nor a query key the mPCC reads gets a
warning, since the mPCC ignores unknown filters and matches every row.
"""
from io import StringIO

import pytest
import requests

from mash.app import MprovShell


class FakeResponse:
  status_code = 200
  text = "[]"

  def json(self):
    return []


class RecordingSession:
  'Records the URL each request would really go to.'
  def __init__(self):
    self.urls = []

  def _send(self, method, url, params=None, **kwargs):
    self.urls.append(requests.Request(method, url, params=params).prepare().url)
    return FakeResponse()

  def get(self, url, **kwargs):
    return self._send("GET", url, **kwargs)

  def delete(self, url, **kwargs):
    return self._send("DELETE", url, **kwargs)


@pytest.fixture
def shell(capsys):
  s = MprovShell()
  s.stdout = StringIO()
  s.variables = {}
  s.mprovURL = "http://mpcc"
  s.models = {
    "systems": {"endpoint": "/systems/", "fields": {
      "id": {}, "hostname": {}, "ipaddress": {}, "systemgroups": {}}},
    "jobs": {"endpoint": "/jobs/", "fields": {"id": {}, "name": {}}},
  }
  s.session = RecordingSession()
  return s


def test_reserved_characters_stay_in_the_value(shell):
  shell.onecmd("retrieve systems hostname=a&ipaddress=1.2.3.4")
  assert shell.session.urls == ["http://mpcc/systems/?hostname=a%26ipaddress%3D1.2.3.4"]


def test_hash_does_not_drop_the_rest_of_the_query(shell):
  shell.onecmd("delete systems hostname=a#b ipaddress=10.0.0.1")
  assert shell.session.urls == ["http://mpcc/systems/?hostname=a%23b&ipaddress=10.0.0.1"]


def test_percent_is_sent_literally(shell):
  shell.onecmd("retrieve systems hostname=50%25")
  assert shell.session.urls == ["http://mpcc/systems/?hostname=50%2525"]


def test_plain_query_is_unchanged(shell):
  shell.onecmd("retrieve systems hostname=node01  ipaddress=10.0.0.1")
  assert shell.session.urls == ["http://mpcc/systems/?hostname=node01&ipaddress=10.0.0.1"]


def test_id_goes_in_the_path_encoded(shell):
  shell.onecmd("retrieve systems id=5")
  shell.onecmd("delete systems pk=a/b")
  assert shell.session.urls == [
    "http://mpcc/systems/5/?id=5",
    "http://mpcc/systems/a%2Fb/?pk=a%2Fb",
  ]


def test_no_args_sends_no_query(shell):
  shell.onecmd("retrieve systems")
  assert shell.session.urls == ["http://mpcc/systems/"]


def test_json_value_is_encoded(shell):
  shell.onecmd('retrieve jobs params={"imageId":"x&y"}')
  assert shell.session.urls == [
    "http://mpcc/jobs/?params=%7B%22imageId%22%3A%22x%26y%22%7D"]


@pytest.mark.parametrize("token", ["garbage", "=value"])
def test_token_without_a_key_is_refused(shell, capsys, token):
  shell.variables["MPROV_RESULT"] = ["stale"]
  shell.onecmd(f"retrieve systems {token} hostname=a")
  assert shell.session.urls == []
  assert f"expected <field>=<value>, got '{token}'" in capsys.readouterr().err
  assert shell.variables["MPROV_RESULT"] is None


def test_unknown_key_warns_but_is_sent(shell, capsys):
  shell.onecmd("retrieve systems hostnme=a")
  assert shell.session.urls == ["http://mpcc/systems/?hostnme=a"]
  err = capsys.readouterr().err
  assert "Model systems has no field hostnme" in err


@pytest.mark.parametrize("query", [
  "detail=1", "self=1", "search=node", "hostname=a",
  "module=image-update", "status=1", "jobserver=2",
])
def test_keys_the_mpcc_reads_do_not_warn(shell, capsys, query):
  model = "jobs" if query.split("=")[0] in ("module", "status", "jobserver") else "systems"
  shell.onecmd(f"retrieve {model} {query}")
  assert len(shell.session.urls) == 1
  assert "Warning" not in capsys.readouterr().err
