import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('redis_aof', Path(__file__).parents[1] /
    'setup/geseidl_edition/components/redis_aof.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize('prefix', [b'REDIS0012', b'*2\r\n'])
def test_binary_snapshot_refused_before_persisting_configuration(tmp_path, monkeypatch, prefix):
    directory = tmp_path / 'appendonlydir'
    directory.mkdir()
    (directory / 'appendonly.aof.manifest').write_text('file appendonly.aof.1.base.aof seq 1 type b\n')
    (directory / 'appendonly.aof.1.base.aof').write_bytes(prefix)
    calls = []

    def redis(*args):
        calls.append(args)
        if args == ('PING',):
            return 'PONG'
        if args == ('INFO', 'persistence'):
            return 'aof_enabled:0\naof_rewrite_in_progress:0\naof_rewrite_scheduled:0\naof_last_bgrewrite_status:ok\naof_base_size:99'
        if args[:2] == ('CONFIG', 'GET'):
            values = {'dir': str(tmp_path), 'appenddirname': 'appendonlydir', 'appendfilename': 'appendonly.aof'}
            return args[2] + '\n' + values[args[2]]
        return 'OK'

    monkeypatch.setattr(module.os, 'geteuid', lambda: 0, raising=False)
    monkeypatch.setattr(module, 'command', redis)
    if prefix.startswith(b'REDIS'):
        with pytest.raises(RuntimeError, match='binary RDB'):
            module.prepare()
        assert ('CONFIG', 'REWRITE') not in calls
    else:
        assert module.prepare()['plain_command_base']
        assert calls.index(('CONFIG', 'SET', 'appendonly', 'yes')) < calls.index(('CONFIG', 'REWRITE'))


def test_offline_or_refused_server_does_not_change_persistence(monkeypatch):
    calls = []
    monkeypatch.setattr(module.os, 'geteuid', lambda: 0, raising=False)
    monkeypatch.setattr(module, 'command', lambda *args: calls.append(args) or 'NOAUTH Authentication required')
    with pytest.raises(RuntimeError, match='unavailable'):
        module.prepare()
    assert calls == [('PING',)]
