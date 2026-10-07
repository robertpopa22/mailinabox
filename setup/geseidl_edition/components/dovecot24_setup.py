#!/usr/bin/env python3
"""Reconcile an operator-tested Dovecot 2.4 profile during edition setup."""
import argparse
import copy
import grp
import json
import os
from pathlib import Path
import subprocess
import tempfile

from dovecot24 import convert

PROFILE = Path('/etc/mailinabox-geseidl/dovecot24.json')


def reconcile(storage_root, hostname):
    if os.geteuid() != 0:
        raise PermissionError('Edition setup requires root')
    for path in [PROFILE.parent, PROFILE]:
        if path.is_symlink() or path.stat().st_uid != 0 or path.stat().st_mode & 0o077:
            raise PermissionError('Profile must be root-owned and private')
    profile = json.loads(PROFILE.read_text())
    if profile.get('schema') != 1:
        raise ValueError('Unsupported edition profile schema')
    parameters = copy.deepcopy(profile['parameters'])
    previous = profile['storage_root'].rstrip('/')
    replacement = storage_root.rstrip('/')
    source = profile['source'].replace(previous + '/', replacement + '/')
    source = source.replace('postmaster@' + profile['primary_hostname'], 'postmaster@' + hostname)
    for section in ['sql', 'private']:
        for key, value in parameters[section].items():
            if key != 'auth_policy_hash_nonce':
                parameters[section][key] = value.replace(previous + '/', replacement + '/')
    desired = convert(source, parameters['sql'], parameters['private'], profile['storage_version'])
    destination = Path('/etc/dovecot/dovecot.conf')
    with tempfile.NamedTemporaryFile(mode='w', dir=destination.parent, prefix='.geseidl24-', delete=False) as stream:
        stream.write(desired)
        candidate = Path(stream.name)
    try:
        subprocess.run(['doveconf', '-c', str(candidate), '-n'], check=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        changed = destination.read_bytes() != candidate.read_bytes()
        if changed:
            os.chown(candidate, 0, grp.getgrnam('dovecot').gr_gid)
            candidate.chmod(0o640)
            os.replace(candidate, destination)
        print('Dovecot 2.4 edition configuration ' + ('reconciled' if changed else 'unchanged'))
    finally:
        if candidate.exists():
            candidate.unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage-root', required=True)
    parser.add_argument('--primary-hostname', required=True)
    args = parser.parse_args()
    reconcile(args.storage_root, args.primary_hostname)
