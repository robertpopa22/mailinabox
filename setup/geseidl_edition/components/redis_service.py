#!/usr/bin/env python3
"""Explicitly preserve the reviewed distribution Redis service before switching origin."""
import argparse
import hashlib
import json
import os
from pathlib import Path


def render(native):
    sections = native.split('[Service]')
    if len(sections) != 2:
        raise ValueError('Expected one native Redis service section')
    service = sections[1].split('[Install]')[0].strip()
    commands = [line for line in service.splitlines() if line.startswith('ExecStart=')]
    reviewed = {'ExecStart=/usr/bin/redis-server /etc/redis/redis.conf',
                'ExecStart=/usr/bin/redis-server /etc/redis/redis.conf --supervised systemd --daemonize no'}
    if len(commands) != 1 or commands[0] not in reviewed:
        raise ValueError('Unreviewed native Redis command')
    return '# Reviewed distribution service retained across publisher package origins.\n[Service]\nExecStart=\n' + service + '\n'


def preserve(source):
    if os.geteuid() != 0:
        raise PermissionError('Service preservation requires root')
    info = source.stat()
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError('Untrusted native service file')
    content = render(source.read_text()).encode()
    target = Path('/etc/systemd/system/redis-server.service.d/geseidl-native-service.conf')
    if target.exists() and target.read_bytes() != content:
        raise ValueError('Conflicting existing service profile')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    target.chmod(0o644)
    return {'service_profile_preserved': True, 'sha256': hashlib.sha256(content).hexdigest(),
            'service_restarted': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preserve-service', action='store_true', required=True)
    parser.add_argument('--native-unit', type=Path, default=Path('/usr/lib/systemd/system/redis-server.service'))
    args = parser.parse_args()
    os.umask(0o077)
    print(json.dumps(preserve(args.native_unit)))
