#!/usr/bin/env python3
"""Build an optional NSD release package while retaining native service integration.

Build only: never install a package or modify running services. The caller supplies
an authenticated distribution package as the integration baseline. The resulting
package is a Geseidl release-channel artifact, not an upstream installation default.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

VERSION = '4.15.2'
SOURCE_SHA256 = 'bb4d57753c2cc2a641c92dab1021016d25fb4b972920bf4f0bbb8c40c1a9cce2'


def command(args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def replace_field(control, name, value):
    if '\n' in value or '\r' in value:
        raise ValueError('Control field contains a newline')
    pattern = r'^' + re.escape(name) + r':[^\n]*(?:\n[ \t][^\n]*)*'
    replacement = name + ': ' + value
    if re.search(pattern, control, re.M):
        return re.sub(pattern, lambda match: replacement, control, flags=re.M)
    return control.rstrip() + '\n' + replacement + '\n'


def build(work, source_archive, baseline, maintainer):
    if work.exists() or work.is_symlink():
        raise ValueError('Build directory already exists; inspect it before retry')
    if not re.fullmatch(r'[^<>\r\n]+ <[^<>\r\n@]+@[^<>\r\n@]+>', maintainer):
        raise ValueError('Expected a maintainer name and email')
    source_hash = hashlib.sha256(source_archive.read_bytes()).hexdigest()
    if source_hash != SOURCE_SHA256:
        raise ValueError('Publisher source hash mismatch')
    if command(['dpkg-deb', '--field', str(baseline), 'Package']) != 'nsd':
        raise ValueError('Expected a native NSD integration package')
    work.mkdir(mode=0o700, parents=True)
    with tarfile.open(source_archive) as archive:
        archive.extractall(work, filter='data')
    source = work / ('nsd-' + VERSION)
    # NSD appends /nsd to sysconfdir itself; /etc/nsd would duplicate it.
    options = ['./configure', '--prefix=/usr', '--sysconfdir=/etc',
        '--localstatedir=/var', '--with-zonesdir=/etc/nsd/zones',
        '--with-pidfile=/run/nsd/nsd.pid', '--with-xfrdfile=/var/lib/nsd/xfrd.state',
        '--with-zonelistfile=/var/lib/nsd/zone.list', '--with-user=nsd',
        '--enable-systemd', '--with-ssl']
    with (work / 'build.log').open('w') as log:
        for args in [options, ['make', '-j2']]:
            subprocess.run(args, cwd=source, stdout=log, stderr=subprocess.STDOUT, check=True)
    if not re.search(r'^#define CONFIGFILE "/etc/nsd/nsd\.conf"$',
                     (source / 'config.h').read_text(), re.M):
        raise RuntimeError('Compiled default configuration path does not match the native service')
    stage = work / 'native-package'
    subprocess.run(['dpkg-deb', '--raw-extract', str(baseline), str(stage)], check=True)
    payload = work / 'new-payload'
    with (work / 'install.log').open('w') as log:
        subprocess.run(['make', 'DESTDIR=' + str(payload), 'install'], cwd=source,
            stdout=log, stderr=subprocess.STDOUT, check=True)
    # Retain the distribution service, maintainer scripts, conffiles and existing
    # integration. Replace daemon/CLI/man pages, not managed configuration.
    for tree in ['usr/sbin', 'usr/share/man']:
        shutil.copytree(payload / tree, stage / tree, dirs_exist_ok=True)
    control_path = stage / 'DEBIAN/control'
    control = control_path.read_text()
    release = VERSION + '+geseidl2'
    control = replace_field(control, 'Version', release)
    control = replace_field(control, 'Maintainer', maintainer)
    control = replace_field(control, 'X-Upstream-Source-SHA256', SOURCE_SHA256)
    installed_kib = sum(p.stat().st_size for p in stage.rglob('*') if p.is_file()) // 1024
    control = replace_field(control, 'Installed-Size', str(installed_kib))
    control_path.write_text(control)
    checksums = []
    for path in sorted(stage.rglob('*')):
        if path.is_file() and not path.is_symlink() and 'DEBIAN' not in path.relative_to(stage).parts:
            checksums.append(hashlib.md5(path.read_bytes()).hexdigest() + '  ' + path.relative_to(stage).as_posix())
    (stage / 'DEBIAN/md5sums').write_text('\n'.join(checksums) + '\n')
    output = work / ('nsd_' + release + '_' + command(['dpkg-deb', '--field', str(baseline), 'Architecture']) + '.deb')
    subprocess.run(['dpkg-deb', '--build', str(stage), str(output)], check=True)
    result = {'version': VERSION, 'package_version': release, 'source_sha256': source_hash,
        'baseline_sha256': hashlib.sha256(baseline.read_bytes()).hexdigest(),
        'package_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
        'native_integration_retained': True, 'installed': False}
    (work / 'build-manifest.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--maintainer', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    build(args.work.resolve(), args.source.resolve(), args.baseline.resolve(), args.maintainer)
