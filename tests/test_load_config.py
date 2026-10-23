"""Regression tests for MprovShell.load_config config shapes (MASH-013).

Runs with the stdlib alone: the jinja2/requests imports of mash.app are
stubbed for the test process when they are not installed, because
load_config itself only needs yaml.
"""
import io
import contextlib
import sys
import tempfile
import types
import unittest
from pathlib import Path

for _name in ("jinja2", "requests"):
    if _name not in sys.modules:
        try:
            __import__(_name)
        except ImportError:
            _m = types.ModuleType(_name)
            if _name == "jinja2":
                _m.Environment = object
                _m.BaseLoader = object
            else:
                _m.Session = type("Session", (), {})
            sys.modules[_name] = _m

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mash.app import MprovShell  # noqa: E402

GLOBAL_FORMAT = "apikey: <api-key>"


class LoadConfigShapes(unittest.TestCase):
    def _shell_with(self, text):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = Path(tmp.name) / "mash.yaml"
        cfg.write_text(text, encoding="utf-8")
        shell = MprovShell()
        # load_config() rescans self.configfiles and derives configfile from
        # it, so pin the search list rather than configfile itself.
        shell.configfiles = [str(cfg)]
        return shell

    def _load(self, shell):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            ok = shell.load_config()
        return ok, stderr.getvalue()

    def test_mapping_shape_loads(self):
        """'global:' as a top-level key is the obvious way to write the file."""
        shell = self._shell_with("global:\n  apikey: k\n  mprovURL: u\n")
        ok, err = self._load(shell)
        self.assertTrue(ok)
        self.assertEqual(
            shell.config_data,
            {"global": {"apikey": "k", "mprovURL": "u"}},
        )
        self.assertEqual(err, "")

    def test_list_shape_still_loads(self):
        """The historical top-level list of mappings keeps working."""
        shell = self._shell_with("- global:\n    apikey: k\n    mprovURL: u\n")
        ok, err = self._load(shell)
        self.assertTrue(ok)
        self.assertEqual(
            shell.config_data,
            {"global": {"apikey": "k", "mprovURL": "u"}},
        )

    def test_list_without_global_section_reports_config_error(self):
        shell = self._shell_with("- other:\n    x: 1\n")
        ok, err = self._load(shell)
        self.assertFalse(ok)
        self.assertIn("no 'global' section", err)
        self.assertIn(GLOBAL_FORMAT, err)

    def test_scalar_top_level_reports_config_error(self):
        shell = self._shell_with("just a string\n")
        ok, err = self._load(shell)
        self.assertFalse(ok)
        self.assertIn("expected a mapping or a list of mappings", err)
        self.assertIn("found str", err)

    def test_list_of_scalars_reports_config_error(self):
        shell = self._shell_with("- a\n- b\n")
        ok, err = self._load(shell)
        self.assertFalse(ok)
        self.assertIn("expected a mapping or a list of mappings", err)
        self.assertIn("list containing a str", err)

    def test_global_not_a_mapping_reports_config_error(self):
        shell = self._shell_with("global: not-a-mapping\n")
        ok, err = self._load(shell)
        self.assertFalse(ok)
        self.assertIn("no 'global' section", err)


if __name__ == "__main__":
    unittest.main()
