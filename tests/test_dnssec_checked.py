import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


def test_success_quiet_and_failures_visible(monkeypatch, capsys):
    log = Mock(LOG_INFO=6)
    monkeypatch.setitem(sys.modules, 'syslog', log)
    spec = importlib.util.spec_from_file_location('dnssec_checked', Path(__file__).parents[1] / 'tools/dnssec_checked.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='updated\n', stderr=''))
    assert module.main() == 0
    assert capsys.readouterr() == ('', '')
    log.syslog.assert_called_once_with(6, 'updated')
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=2, stdout='diagnostic\n', stderr='failure\n'))
    assert module.main() == 2
    captured = capsys.readouterr()
    assert 'diagnostic' in captured.out and 'failure' in captured.err
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=0, stdout='', stderr='warning\n'))
    assert module.main() == 0
    assert capsys.readouterr().err == 'warning\n'
    def timeout(*a, **k):
        raise module.subprocess.TimeoutExpired('dns_update', 600)
    monkeypatch.setattr(module.subprocess, 'run', timeout)
    assert module.main() == 1
    assert 'TimeoutExpired' in capsys.readouterr().err
