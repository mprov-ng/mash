"""Plugin dispatch must not mangle arguments containing the plugin name.

mprov-ng/mash#23: default() splits the plugin token off the front of the
line, so a subsequent replace() of the plugin name over the remaining
arguments corrupts legitimate arguments such as 'power on bmc001'.
"""
import importlib.util
import sys
import types

import pytest

from mash.app import MprovShell


@pytest.fixture
def recorder(monkeypatch):
    """Register a stub plugin 'mash.plugins.recorder' that records its dispatch."""
    received = []

    class PluginCMD:
        def __init__(self, shell):
            self.shell = shell

        def onecmd(self, line):
            received.append(line)

    name = "mash.plugins.recorder"
    mod = types.ModuleType(name)
    mod.__spec__ = importlib.util.spec_from_loader(name, loader=None)
    setattr(mod, "PluginCMD", PluginCMD)
    monkeypatch.setitem(sys.modules, name, mod)
    return received


def test_args_containing_plugin_name_reach_plugin_verbatim(recorder):
    shell = MprovShell()
    shell.default("recorder power on recorder001")
    assert recorder == ["power on recorder001"]


def test_bare_plugin_invocation_receives_empty_args(recorder):
    shell = MprovShell()
    shell.default("recorder")
    assert recorder == [""]
