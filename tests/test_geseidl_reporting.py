import ast
import importlib.util
from pathlib import Path

import pytest

from management.geseidl_edition.status_changes import (
    held_apt_updates, parse_apt_updates, probe_outbound_smtp,
    render_category_changes, report_software_updates,
)


class Output:
    def __init__(self):
        self.lines = []
    def __getattr__(self, method):
        return lambda *args, **kwargs: self.lines.append((method, list(args), kwargs))


def test_fragmented_changes_are_grouped_and_complete():
    before = [('print_error', ['There are 45 software packages that can be updated.'], {}),
              ('print_line', ['unchanged (1)'], {}),
              ('print_line', ['tail (1)'], {})]
    after = [('print_error', ['There are 52 software packages that can be updated.'], {}),
             ('print_line', ['redis-server (2)'], {}),
             ('print_line', ['unchanged (1)'], {}),
             ('print_line', ['libfreetype6 (2)'], {}),
             ('print_line', ['tail (1)'], {}),
             ('print_line', ['sg3-utils (2)'], {})]
    output = Output()
    render_category_changes('System', before, after, output)
    headings = [line for line in output.lines if line[0] == 'add_heading']
    assert len(headings) == 2
    assert 'Previously' in headings[0][1][0] and 'Currently' in headings[1][1][0]
    values = [line[1][0] for line in output.lines]
    assert all(text in values for text in [before[0][1][0], after[0][1][0],
               'redis-server (2)', 'libfreetype6 (2)', 'sg3-utils (2)'])
    assert 'unchanged (1)' not in values


def test_health_counter_churn_remains_quiet_and_degradation_visible():
    output = Output()
    before = [('print_ok', ['rspamd active: 1 scanned'], {})]
    render_category_changes('System', before, [('print_ok', ['rspamd active: 2 scanned'], {})], output)
    assert output.lines == []
    render_category_changes('System', before, [('print_error', ['rspamd is not running'], {})], output)
    assert any(line[0] == 'print_error' for line in output.lines)


@pytest.mark.parametrize('code', [0, 1])
def test_smtp_diagnostics_are_captured_but_result_is_preserved(code):
    def shell(method, args, **kwargs):
        assert method == 'check_output' and kwargs['capture_stderr'] and kwargs['trap']
        assert args[-1] == '25'
        return code, 'Connection succeeded!'
    assert probe_outbound_smtp(shell) == (code, code)


def test_apt_count_uses_only_install_records_including_new_dependencies():
    packages = parse_apt_updates('''Inst redis-tools [1:7.0] (1:7.1 Ubuntu [amd64])
Conf redis-tools (1:7.1 Ubuntu [amd64])
Inst linux-image-new (6.8.0-146 Ubuntu [amd64])
W: diagnostic line is not a package
2 upgraded, 1 newly installed
''')
    assert packages == [
        {'package': 'redis-tools', 'current_version': '1:7.0', 'version': '1:7.1'},
        {'package': 'linux-image-new', 'current_version': '', 'version': '6.8.0-146'},
    ]
    with pytest.raises(ValueError):
        parse_apt_updates('Inst unreadable-record')


def held_shell(method, args, **kwargs):
    if args[0].endswith('apt-mark'):
        return 'held-agent\n'
    if args[0].endswith('apt-cache'):
        return 'held-agent:\n  Installed: 1.0\n  Candidate: 2.0\n  Version table:\n'
    assert args[0].endswith('dpkg') and args[-3:] == ['2.0', 'gt', '1.0']
    return 0, 0


def test_held_updates_are_explicit_without_false_up_to_date_or_installable_error():
    assert held_apt_updates(held_shell)[0]['package'] == 'held-agent'
    output = Output()
    report_software_updates([], False, output, held_shell)
    assert any(line[0] == 'print_warning' for line in output.lines)
    assert any('held-agent (1.0 -> 2.0; held)' in line[1] for line in output.lines)
    assert not any(line[0] in {'print_ok', 'print_error'} for line in output.lines)


def test_reboot_and_installable_updates_are_both_visible():
    output = Output()
    report_software_updates([{'package': 'a', 'current_version': '1', 'version': '2'}],
                            True, output, lambda *args, **kwargs: '')
    errors = [line[1][0] for line in output.lines if line[0] == 'print_error']
    assert len(errors) == 2 and 'reboot' in errors[0] and '1 software package' in errors[1]


def test_unknown_hold_status_never_becomes_false_green():
    def broken(*args, **kwargs):
        raise RuntimeError('not available')
    output = Output()
    report_software_updates([], False, output, broken)
    assert [line[0] for line in output.lines] == ['print_warning']


def test_reporting_hooks_apply_and_remove_idempotently_on_real_source(tmp_path):
    root = Path(__file__).parents[1]
    spec = importlib.util.spec_from_file_location('report_applier', root / 'management/geseidl_edition/apply_overlay.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hooks = [hook for hook in module.HOOKS if hook['name'] in {
        'status_checks:quiet-smtp-probe', 'status_checks:apt-install-records',
        'status_checks:held-update-policy', 'status_checks:group-category-changes'}]
    assert len(hooks) == 4
    source = (root / 'management/status_checks.py').read_text()
    (tmp_path / 'status_checks.py').write_text(source)
    module.MGMT_DIR = str(tmp_path)
    for hook in hooks:
        assert module.remove_hook(hook) == 'removed'
    original = (tmp_path / 'status_checks.py').read_text()
    for hook in hooks:
        assert module.apply_hook(hook) == 'applied'
        assert module.apply_hook(hook) == 'already'
    ast.parse((tmp_path / 'status_checks.py').read_text())
    for hook in hooks:
        assert module.remove_hook(hook) == 'removed'
        assert module.remove_hook(hook) == 'absent'
    assert (tmp_path / 'status_checks.py').read_text() == original
