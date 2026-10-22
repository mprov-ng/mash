"""Which config file 'connect' reads (mprov-ng/mash#7)."""
import os

import pytest

from mash.app import MprovShell

# Shaped like the job server's /etc/mprov/jobserver.yaml, '!include' and all.
JOBSERVER_YAML = """\
- global:
    mprovURL: "http://mpcc-from-jobserver/"
    apikey: 'jobserver-key'
    heartbeatInterval: 10
    jobmodules:
      - dnsmasq

# include any plugin yamls.
- !include plugins/*.yaml
"""


def mash_yaml(url):
  return f"- global:\n    mprovURL: \"{url}\"\n    apikey: 'mash-key'\n"


@pytest.fixture
def paths(tmp_path):
  'The three config files, in order of preference.  None exist yet.'
  return [tmp_path / "home.yaml", tmp_path / "mash.yaml", tmp_path / "jobserver.yaml"]


@pytest.fixture
def shell(paths):
  s = MprovShell()
  s.configfiles = [str(p) for p in paths]
  return s


def test_falls_back_to_jobserver_yaml(shell, paths):
  paths[2].write_text(JOBSERVER_YAML)
  assert shell.load_config()
  assert shell.configfile == str(paths[2])
  assert shell.config_data["global"]["mprovURL"] == "http://mpcc-from-jobserver/"
  assert shell.config_data["global"]["apikey"] == "jobserver-key"


def test_mash_yaml_wins_over_jobserver_yaml(shell, paths):
  paths[1].write_text(mash_yaml("http://mpcc-from-mash/"))
  paths[2].write_text(JOBSERVER_YAML)
  assert shell.load_config()
  assert shell.config_data["global"]["mprovURL"] == "http://mpcc-from-mash/"


def test_home_config_wins_over_both(shell, paths):
  paths[0].write_text(mash_yaml("http://mpcc-from-home/"))
  paths[1].write_text(mash_yaml("http://mpcc-from-mash/"))
  paths[2].write_text(JOBSERVER_YAML)
  assert shell.load_config()
  assert shell.config_data["global"]["mprovURL"] == "http://mpcc-from-home/"


def test_home_path_is_expanded(tmp_path, monkeypatch):
  monkeypatch.setenv("HOME", str(tmp_path))
  (tmp_path / ".mprov-mash.yaml").write_text(mash_yaml("http://mpcc-from-home/"))
  shell = MprovShell()
  assert shell.load_config()
  assert shell.configfile == str(tmp_path / ".mprov-mash.yaml")


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read any file")
def test_unreadable_file_is_skipped(shell, paths):
  paths[1].write_text(mash_yaml("http://mpcc-from-mash/"))
  paths[1].chmod(0)
  paths[2].write_text(JOBSERVER_YAML)
  assert shell.load_config()
  assert shell.configfile == str(paths[2])


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read any file")
def test_error_names_every_file_tried(shell, paths, capsys):
  paths[2].write_text(JOBSERVER_YAML)
  paths[2].chmod(0)
  assert not shell.load_config()
  err = capsys.readouterr().err
  assert "Unable to find a readable config file." in err
  assert f"{paths[0]}: not found" in err
  assert f"{paths[1]}: not found" in err
  assert f"{paths[2]}: permission denied" in err


def test_connect_without_config_does_not_connect(shell, monkeypatch, capsys):
  called = []
  monkeypatch.setattr(shell, "_connectToMPCC", lambda *a: called.append(a))
  shell.onecmd("connect")
  assert called == []
  assert "Unable to find a readable config file." in capsys.readouterr().err


def test_connect_uses_jobserver_yaml(shell, paths, monkeypatch):
  paths[2].write_text(JOBSERVER_YAML)
  called = []
  monkeypatch.setattr(shell, "_connectToMPCC", lambda *a: called.append(a))
  shell.onecmd("connect")
  assert called == [("Api-Key jobserver-key",)]
  assert shell.mprovURL == "http://mpcc-from-jobserver/"
