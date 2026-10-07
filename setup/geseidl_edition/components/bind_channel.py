#!/usr/bin/env python3
"""Stage ISC stable Ubuntu packages; never install or restart services."""
import argparse
from datetime import datetime, timezone
import email.parser
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

FINGERPRINT = '66150059ED19A2882208E278A36654A4FDD4630D'
REPOSITORY = 'https://ppa.launchpadcontent.net/isc/bind/ubuntu/'


def download(url, target, expected=None):
    data = urllib.request.urlopen(url, timeout=60).read()
    digest = hashlib.sha256(data).hexdigest()
    if expected and digest != expected:
        raise ValueError('Publisher metadata checksum mismatch')
    target.write_bytes(data)
    return digest


def stage(work, version):
    work.mkdir(mode=0o700, parents=True, exist_ok=False)
    home = work / 'gnupg'
    home.mkdir(mode=0o700)
    key = work / 'isc-bind.asc'
    download('https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x' + FINGERPRINT, key)
    details = subprocess.check_output(['gpg', '--homedir', str(home), '--batch',
        '--with-colons', '--show-keys', str(key)], text=True, stderr=subprocess.DEVNULL)
    fingerprints = [line.split(':')[9] for line in details.splitlines() if line.startswith('fpr:')]
    if not fingerprints or fingerprints[0] != FINGERPRINT:
        raise ValueError('Unexpected ISC repository signing key')
    keyring = work / 'isc-bind.gpg'
    subprocess.run(['gpg', '--homedir', str(home), '--batch', '--dearmor',
        '--output', str(keyring), str(key)], check=True, capture_output=True)
    release = work / 'InRelease'
    download(REPOSITORY + 'dists/noble/InRelease', release)
    verified = work / 'Release'
    result = subprocess.run(['gpgv', '--homedir', str(home), '--keyring', str(keyring),
        '--output', str(verified), str(release)], capture_output=True, text=True)
    (work / 'signature.log').write_text(result.stderr)
    result.check_returncode()
    metadata = email.parser.Parser().parsestr(verified.read_text())
    if metadata['Codename'] != 'noble' or metadata['Origin'] != 'LP-PPA-isc-bind':
        raise ValueError('Unexpected Ubuntu release')
    index_path = 'main/binary-amd64/Packages.gz'
    index_hash = next(line.split()[0] for line in metadata['SHA256'].splitlines()
        if line.split() and line.split()[-1] == index_path)
    index = work / 'Packages.gz'
    download(REPOSITORY + 'dists/noble/' + index_path, index, index_hash)
    paragraphs = gzip.decompress(index.read_bytes()).decode().strip().split('\n\n')
    installed = subprocess.check_output(['dpkg-query', '-W', '-f=${binary:Package} ${db:Status-Status}\n',
        'bind9*'], text=True).splitlines()
    wanted = {line.split()[0].split(':')[0] for line in installed if line.endswith(' installed')}
    packages = []
    for paragraph in paragraphs:
        record = email.parser.Parser().parsestr(paragraph)
        if record['Package'] not in wanted or record['Architecture'] not in ('all', 'amd64'):
            continue
        if not record['Version'].startswith('1:' + version + '-'):
            raise ValueError('Publisher stable package differs from reviewed target')
        target = work / Path(record['Filename']).name
        digest = download(REPOSITORY + record['Filename'], target, record['SHA256'])
        packages.append({'package': record['Package'], 'version': record['Version'],
            'filename': target.name, 'sha256': digest, 'depends': record['Depends']})
    if {item['package'] for item in packages} != wanted:
        raise ValueError('Not all installed BIND packages are available')
    manifest = {'verified_at': datetime.now(timezone.utc).isoformat(),
        'repository': REPOSITORY, 'key_fingerprint': FINGERPRINT,
        'release_date': metadata['Date'], 'packages': packages,
        'live_services_changed': False}
    (work / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest))


def enable_channel(work, version):
    """Opt-in repository persistence after operator-tested migration."""
    if os.geteuid() != 0:
        raise PermissionError('Channel configuration requires root')
    os_release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if os_release.get('ID', '').strip('"') != 'ubuntu' or os_release.get('VERSION_ID', '').strip('"') != '24.04':
        raise ValueError('Only the reviewed Ubuntu 24.04 channel is supported')
    manifest = json.loads((work / 'manifest.json').read_text())
    if manifest['repository'] != REPOSITORY or manifest['key_fingerprint'] != FINGERPRINT:
        raise ValueError('Unexpected channel manifest')
    if not all(item['version'].startswith('1:' + version + '-') for item in manifest['packages']):
        raise ValueError('Unexpected reviewed version')
    home = work / 'gnupg'
    details = subprocess.check_output(['gpg', '--homedir', str(home), '--batch',
        '--with-colons', '--show-keys', str(work / 'isc-bind.gpg')], text=True, stderr=subprocess.DEVNULL)
    if next(line.split(':')[9] for line in details.splitlines() if line.startswith('fpr:')) != FINGERPRINT:
        raise ValueError('Unexpected signing key')
    key = Path('/etc/apt/keyrings/geseidl-isc-bind.gpg')
    source = Path('/etc/apt/sources.list.d/geseidl-isc-bind.sources')
    preference = Path('/etc/apt/preferences.d/geseidl-isc-bind')
    targets = {
        key: (work / 'isc-bind.gpg').read_bytes(),
        source: ('Types: deb\nURIs: ' + REPOSITORY + '\nSuites: noble\nComponents: main\n'
            'Architectures: amd64\nSigned-By: ' + str(key) + '\n').encode(),
        preference: ('Package: bind9 bind9-*\nPin: release o=LP-PPA-isc-bind\nPin-Priority: 600\n\n'
            'Package: *\nPin: release o=LP-PPA-isc-bind\nPin-Priority: -1\n').encode()}
    for target, content in targets.items():
        if target.exists() and target.read_bytes() != content:
            raise ValueError('Existing channel file differs: ' + str(target))
    for target, content in targets.items():
        target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        target.write_bytes(content)
        target.chmod(0o644)
    print(json.dumps({'channel_enabled': True, 'package_scope': 'bind9 bind9-*',
        'services_restarted': False, 'packages_installed': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--enable-channel', action='store_true',
        help='Persist the scoped repository after separately testing migration; installs no packages')
    args = parser.parse_args()
    if args.enable_channel:
        enable_channel(args.work, args.version)
    else:
        stage(args.work, args.version)
