#!/usr/bin/env python3
"""Explicitly prepare a running Redis for recovery through a plain-command AOF.

Run before replacing Redis. Editing appendonly in an offline config alone is
unsafe: the running server must create a complete AOF from its current dataset.
This operator tool does not install packages or restore earlier data.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time


def command(*arguments):
    return subprocess.check_output(['redis-cli', '-h', '127.0.0.1', '-p', '6379',
        '--raw', *arguments], text=True).rstrip('\n')


def prepare(timeout=180):
    if os.geteuid() != 0:
        raise PermissionError('Persistence preparation requires root')
    if command('PING') != 'PONG':
        raise RuntimeError('Local Redis is unavailable')
    before = dict(line.split(':', 1) for line in command('INFO', 'persistence').splitlines()
                  if ':' in line)
    for setting, value in [('aof-use-rdb-preamble', 'no'), ('appendfsync', 'everysec')]:
        if command('CONFIG', 'SET', setting, value) != 'OK':
            raise RuntimeError('Redis refused persistence setting: ' + setting)
    if before['aof_enabled'] == '0':
        if command('CONFIG', 'SET', 'appendonly', 'yes') != 'OK':
            raise RuntimeError('Redis refused AOF activation')
    else:
        response = command('BGREWRITEAOF')
        if 'started' not in response.lower() and 'scheduled' not in response.lower():
            raise RuntimeError('Redis refused AOF rewrite')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = dict(line.split(':', 1) for line in command('INFO', 'persistence').splitlines()
                     if ':' in line)
        if (state.get('aof_rewrite_in_progress') == '0'
                and state.get('aof_rewrite_scheduled') == '0'
                and state.get('aof_last_bgrewrite_status') == 'ok'
                and int(state.get('aof_base_size', '0')) > 0):
            break
        time.sleep(0.5)
    else:
        raise RuntimeError('AOF preparation incomplete; do not upgrade Redis')
    directory = Path(command('CONFIG', 'GET', 'dir').splitlines()[1])
    subdirectory = command('CONFIG', 'GET', 'appenddirname').splitlines()[1]
    name = command('CONFIG', 'GET', 'appendfilename').splitlines()[1]
    manifest = directory / subdirectory / (name + '.manifest')
    base = [line.split()[1] for line in manifest.read_text().splitlines()
            if line.endswith('type b')]
    if len(base) != 1 or Path(base[0]).name != base[0]:
        raise RuntimeError('Unexpected AOF base manifest')
    with (manifest.parent / base[0]).open('rb') as stream:
        if stream.read(1) != b'*':
            raise RuntimeError('AOF contains a binary RDB preamble; do not upgrade')
    if command('CONFIG', 'REWRITE') != 'OK':
        raise RuntimeError('Persistence settings were not saved')
    return {'aof_ready': True, 'plain_command_base': True, 'appendfsync': 'everysec',
            'earlier_data_restored': False, 'package_installed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-recovery', action='store_true', required=True)
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    print(json.dumps(prepare(args.timeout)))
