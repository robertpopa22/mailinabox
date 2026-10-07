"""Regression tests for APT simulation parsing; stdlib only, no server required."""
import ast
import datetime
from pathlib import Path
import re
import unittest


def load_function(simulation):
    # status_checks imports appliance-only services. Execute the actual function
    # with its shell boundary replaced; do not duplicate its parsing logic.
    source = Path(__file__).parents[1] / 'management/status_checks.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == 'list_apt_updates')
    calls = []
    def shell(method, command):
        calls.append((method, command))
        return simulation if method == 'check_output' else None
    namespace = {'datetime': datetime, 're': re, 'shell': shell, '_apt_updates': None}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
    return namespace, calls


class AptUpdatesTests(unittest.TestCase):
    def test_updates_and_new_dependencies_without_counting_diagnostics(self):
        namespace, calls = load_function('''Inst redis-tools:amd64 [5:7.0] (5:7.1 Ubuntu [amd64])
Conf redis-tools:amd64 (5:7.1 Ubuntu [amd64])
Inst linux-image-new (6.8.0-146 Ubuntu [amd64])
W: repository diagnostic
1 upgraded, 1 newly installed, 0 to remove
''')
        self.assertEqual(namespace['list_apt_updates'](apt_update=False), [
            {'package': 'redis-tools:amd64', 'version': '5:7.1', 'current_version': '5:7.0'},
            {'package': 'linux-image-new', 'version': '6.8.0-146', 'current_version': ''},
        ])
        self.assertEqual(len(calls), 1)

    def test_no_install_records_is_empty(self):
        namespace, _ = load_function('Conf ignored (1 Ubuntu [amd64])\n0 upgraded\n')
        self.assertEqual(namespace['list_apt_updates'](apt_update=False), [])

    def test_malformed_install_record_is_not_reported_as_no_updates(self):
        namespace, _ = load_function('Inst broken-record\n')
        with self.assertRaises(ValueError):
            namespace['list_apt_updates'](apt_update=False)
        self.assertIsNone(namespace['_apt_updates'])

    def test_cached_result_does_not_repeat_package_commands(self):
        namespace, calls = load_function('Inst package [1] (2 Ubuntu [amd64])\n')
        first = namespace['list_apt_updates']()
        self.assertIs(namespace['list_apt_updates'](), first)
        self.assertEqual(len(calls), 2)
        namespace['_apt_updates'] = (datetime.datetime.now() - datetime.timedelta(hours=9), first)
        namespace['list_apt_updates'](apt_update=False)
        self.assertEqual(len(calls), 3)


if __name__ == '__main__':
    unittest.main()
