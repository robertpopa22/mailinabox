#!/usr/bin/env python3
"""Use publisher TLS defaults on Postfix versions deprecating custom DH files."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def cleaned(text, version):
    match = re.match(r'^(\d+)\.(\d+)\.', version)
    if not match:
        raise ValueError('Unrecognised Postfix version')
    if tuple(map(int, match.groups())) < (3, 9):
        return text
    return re.sub(r'^smtpd_tls_dh1024_param_file[ \t]*=.*(?:\n[ \t].*)*\n?',
                  '', text, flags=re.M)


def reconcile(apply=False, config=Path('/etc/postfix/main.cf')):
    version = subprocess.check_output(['postconf', '-h', 'mail_version'],
        text=True, stderr=subprocess.PIPE).strip()
    if config.is_symlink():
        raise ValueError('Refusing a symlinked main configuration')
    info = config.stat()
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError('Expected a root-owned main configuration')
    before = config.read_text()
    after = cleaned(before, version)
    if apply and before != after:
        with tempfile.TemporaryDirectory(prefix='.postfix-tls-', dir=config.parent) as stage:
            candidate = Path(stage) / 'main.cf'
            candidate.write_text(after)
            subprocess.run(['postconf', '-c', stage, '-n'], check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            os.chown(candidate, info.st_uid, info.st_gid)
            candidate.chmod(info.st_mode & 0o777)
            os.replace(candidate, config)
    result = {'version': version, 'changed': before != after,
              'applied': apply, 'tls_certificates_unchanged': True}
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    reconcile(args.apply)
