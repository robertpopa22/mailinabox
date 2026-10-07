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


def regularize_metadata(config_directory=Path('/etc/postfix'), share_directory=Path('/usr/share/postfix')):
    metadata = config_directory / 'makedefs.out'
    if not metadata.is_symlink():
        return False
    source = share_directory / 'makedefs.out'
    if source.is_symlink() or metadata.resolve() != source.resolve():
        raise ValueError('Refusing a non-native metadata link')
    info = source.stat()
    if info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError('Expected protected native metadata')
    contents = source.read_bytes()
    with tempfile.NamedTemporaryFile(prefix='.postfix-metadata-', dir=config_directory, delete=False) as stream:
        candidate = Path(stream.name)
        stream.write(contents)
    try:
        candidate.chmod(0o644)
        os.replace(candidate, metadata)
    finally:
        candidate.unlink(missing_ok=True)
    if metadata.read_bytes() != contents:
        raise RuntimeError('Native metadata content changed')
    return True


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
    current = tuple(map(int, re.match(r'^(\d+)\.(\d+)\.', version).groups())) >= (3, 9)
    regularized = regularize_metadata(config.parent) if apply and current else False
    result = {'version': version, 'changed': before != after,
              'native_metadata_regularized': regularized,
              'applied': apply, 'tls_certificates_unchanged': True}
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    reconcile(args.apply)
