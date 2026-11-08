"""Which config file 'connect' reads (mprov-ng/mash#7, #86).

mash used to fall back to the job server's /etc/mprov/jobserver.yaml and
its shared API key.  From 0.7 the job server has no shared key and people
use their own tokens, so mash reads only its own files (mash#86), and says
so when it finds no config but a job server's.
"""
import os

import pytest

from mash.app import MprovShell


def mash_yaml(url):
  return f"- global:\n    mprovURL: \"{url}\"\n    token: 'mash-token'\n"


@pytest.fixture
def paths(tmp_path):
  'The two config files, in order of preference.  None exist yet.'
  return [tmp_path / "home.yaml", tmp_path / "mash.yaml"]


@pytest.fixture
def shell(paths, tmp_path):
  s = MprovShell()
  s.configfiles = [str(p) for p in paths]
  s.jobserverConfig = str(tmp_path / "jobserver.yaml")
  return s


def test_jobserver_yaml_is_not_read():
  assert MprovShell.configfiles == ["~/.mprov-mash.yaml", "/etc/mprov/mash.yaml"]


def test_reads_mash_yaml(shell, paths):
  paths[1].write_text(mash_yaml("http://mpcc-from-mash/"))
  assert shell.load_config()
  assert shell.configfile == str(paths[1])
  assert shell.config_data["global"]["token"] == "mash-token"


def test_home_config_wins(shell, paths):
  paths[0].write_text(mash_yaml("http://mpcc-from-home/"))
  paths[1].write_text(mash_yaml("http://mpcc-from-mash/"))
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
  paths[0].write_text(mash_yaml("http://mpcc-from-home/"))
  paths[0].chmod(0)
  paths[1].write_text(mash_yaml("http://mpcc-from-mash/"))
  assert shell.load_config()
  assert shell.configfile == str(paths[1])


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read any file")
def test_error_names_every_file_tried(shell, paths, capsys):
  paths[1].write_text(mash_yaml("http://mpcc-from-mash/"))
  paths[1].chmod(0)
  assert not shell.load_config()
  err = capsys.readouterr().err
  assert "Unable to find a readable config file." in err
  assert f"{paths[0]}: not found" in err
  assert f"{paths[1]}: permission denied" in err
  assert "jobserver.yaml" not in err


def test_a_job_servers_config_gets_a_hint(shell, tmp_path, capsys):
  (tmp_path / "jobserver.yaml").write_text("- global:\n    apikey: k\n")
  assert not shell.load_config()
  err = capsys.readouterr().err
  assert "no longer reads the job server's" in err
  assert "save-token" in err


def test_connect_without_config_does_not_connect(shell, monkeypatch, capsys):
  called = []
  monkeypatch.setattr(shell, "_connectToMPCC", lambda *a: called.append(a))
  shell.onecmd("connect")
  assert called == []
  assert "Unable to find a readable config file." in capsys.readouterr().err


def test_connect_uses_the_configs_token(shell, paths, monkeypatch):
  paths[1].write_text(mash_yaml("http://mpcc-from-mash/"))
  called = []
  monkeypatch.setattr(shell, "_connectToMPCC", lambda *a: called.append(a))
  shell.onecmd("connect")
  assert called == [("Token mash-token",)]
  assert shell.mprovURL == "http://mpcc-from-mash"
