"""Tests for the foreach loop list parsing (MASH-014).

Runs on a bare stdlib Python: requests/jinja2/yaml are stubbed, the MprovShell
class itself does not need them until a command that talks to the API runs.
"""
import sys
import types
import unittest
from pathlib import Path


def _stub_module(name):
    module = types.ModuleType(name)
    module.__getattr__ = lambda attr: (lambda *a, **k: None)
    sys.modules[name] = module
    return module


for _name in ('requests', 'jinja2', 'yaml'):
    _stub_module(_name)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from mash.app import MprovShell


class ForeachListParsingTest(unittest.TestCase):
    def _shell(self):
        shell = MprovShell()
        shell.err = lambda msg: None  # quiet; errors assert on state below
        return shell

    def _inline_list(self, shell, list_str):
        shell.do_foreach(f'n in {list_str}')
        return shell.forLoopList

    def test_hash_in_list_items_is_not_a_comment(self):
        # regression for MASH-014: shlex.split(arg, 2) treated the second
        # positional argument as comments=True and dropped everything after '#'
        self.assertEqual(self._inline_list(self._shell(), 'c1 c2 #see-infra'),
                         ['c1', 'c2', '#see-infra'])

    def test_trailing_hash_token_is_kept(self):
        self.assertEqual(self._inline_list(self._shell(), 'a b #c d'),
                         ['a', 'b', '#c', 'd'])

    def test_plain_inline_list(self):
        self.assertEqual(self._inline_list(self._shell(), 'c1 c2 c3'),
                         ['c1', 'c2', 'c3'])

    def test_single_token_is_looked_up_as_a_variable(self):
        # a single token has no space, so it is taken as a variable name by design
        shell = self._shell()
        errors = []
        shell.err = errors.append
        shell.do_foreach('n in only')
        self.assertFalse(shell.inForLoop)
        self.assertTrue(any('only' in e for e in errors))

    def test_loop_state_is_entered(self):
        shell = self._shell()
        shell.do_foreach('n in c1 c2')
        self.assertTrue(shell.inForLoop)
        self.assertEqual(shell.forLoopItemName, 'n')

    def test_missing_in_is_rejected(self):
        shell = self._shell()
        errors = []
        shell.err = errors.append
        shell.do_foreach('n over c1 c2')
        self.assertFalse(shell.inForLoop)
        self.assertTrue(errors)

    def test_variable_list_is_looked_up(self):
        shell = self._shell()
        shell.variables = {'nodes': ['c1', 'c2']}
        shell.do_foreach('n in nodes')
        self.assertEqual(shell.forLoopList, ['c1', 'c2'])


if __name__ == '__main__':
    unittest.main()
