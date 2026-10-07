import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('redis_service', Path(__file__).parents[1] /
    'setup/geseidl_edition/components/redis_service.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize('flags', ['', ' --supervised systemd --daemonize no'])
def test_distribution_command_and_hardening_preserved(flags):
    source = '[Unit]\nAfter=network.target\n[Service]\nExecStart=/usr/bin/redis-server /etc/redis/redis.conf' + flags + '\nPrivateUsers=true\nNoExecPaths=/\nExecPaths=/usr/bin/redis-server /lib\n[Install]\nAlias=redis.service\n'
    result = module.render(source)
    assert 'ExecStart=\nExecStart=/usr/bin/redis-server' in result
    assert 'PrivateUsers=true\nNoExecPaths=/\nExecPaths=/usr/bin/redis-server /lib' in result
    assert '[Install]' not in result


def test_unknown_startup_arguments_refused():
    with pytest.raises(ValueError, match='Unreviewed'):
        module.render('[Service]\nExecStart=/usr/bin/redis-server /etc/redis/redis.conf --loadmodule /tmp/extra.so\n')
