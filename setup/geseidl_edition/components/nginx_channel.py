#!/usr/bin/env python3
"""Stage official stable nginx packages; enable their scoped channel separately."""
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

FINGERPRINT = '573BFD6B3D8FBC641079A6ABABF5BD827BD9BF62'
REPOSITORY = 'https://nginx.org/packages/ubuntu/'


def download(url, path, expected=None):
    with urllib.request.urlopen(url, timeout=60) as response:
        contents = response.read()
    digest = hashlib.sha256(contents).hexdigest()
    if expected and digest != expected:
        raise ValueError('Publisher checksum mismatch')
    path.write_bytes(contents)
    return digest


def stage(work, version):
    work.mkdir(mode=0o700, parents=True, exist_ok=False)
    home = work / 'gnupg'
    home.mkdir(mode=0o700)
    key = work / 'nginx_signing.key'
    download('https://nginx.org/keys/nginx_signing.key', key)
    details = subprocess.check_output(['gpg', '--homedir', str(home), '--batch',
        '--with-colons', '--show-keys', str(key)], text=True, stderr=subprocess.DEVNULL)
    fingerprints = [line.split(':')[9] for line in details.splitlines() if line.startswith('fpr:')]
    if FINGERPRINT not in fingerprints:
        raise ValueError('Published nginx signing key is absent')
    keyring = work / 'nginx.gpg'
    subprocess.run(['gpg', '--homedir', str(home), '--batch', '--dearmor',
        '--output', str(keyring), str(key)], check=True, capture_output=True)
    release = work / 'InRelease'
    download(REPOSITORY + 'dists/noble/InRelease', release)
    verified = work / 'Release'
    result = subprocess.run(['gpgv', '--homedir', str(home), '--keyring', str(keyring),
        '--status-fd', '1', '--output', str(verified), str(release)], capture_output=True, text=True)
    (work / 'signature.log').write_text(result.stderr + result.stdout)
    result.check_returncode()
    metadata = email.parser.Parser().parsestr(verified.read_text())
    if metadata['Codename'] != 'noble' or metadata['Origin'] != 'nginx':
        raise ValueError('Unexpected publisher Ubuntu release')
    index_path = 'nginx/binary-amd64/Packages.gz'
    index_hash = next(line.split()[0] for line in metadata['SHA256'].splitlines()
                      if line.split() and line.split()[-1] == index_path)
    index = work / 'Packages.gz'
    download(REPOSITORY + 'dists/noble/' + index_path, index, index_hash)
    records = [email.parser.Parser().parsestr(paragraph) for paragraph in
               gzip.decompress(index.read_bytes()).decode().strip().split('\n\n')]
    candidates = [record for record in records if record['Package'] == 'nginx'
                  and record['Architecture'] == 'amd64' and record['Version'].startswith(version + '-')]
    if len(candidates) != 1:
        raise ValueError('Reviewed stable nginx package missing or ambiguous')
    record = candidates[0]
    target = work / Path(record['Filename']).name
    digest = download(REPOSITORY + record['Filename'], target, record['SHA256'])
    manifest = {'verified_at': datetime.now(timezone.utc).isoformat(),
        'repository': REPOSITORY, 'published_key': FINGERPRINT,
        'release_date': metadata['Date'],
        'signers': [line for line in result.stdout.splitlines() if 'VALIDSIG' in line],
        'packages': [{'package': 'nginx', 'version': record['Version'], 'filename': target.name,
                      'sha256': digest, 'depends': record['Depends']}], 'live_services_changed': False}
    (work / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest))


def enable(work, version):
    if os.geteuid() != 0:
        raise PermissionError('Channel configuration requires root')
    release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if release.get('ID', '').strip('"') != 'ubuntu' or release.get('VERSION_ID', '').strip('"') != '24.04':
        raise ValueError('Only the reviewed Ubuntu 24.04 channel is supported')
    manifest = json.loads((work / 'manifest.json').read_text())
    if manifest['repository'] != REPOSITORY or manifest['published_key'] != FINGERPRINT:
        raise ValueError('Unexpected publisher manifest')
    if not all(item['version'].startswith(version + '-') for item in manifest['packages']):
        raise ValueError('Unexpected reviewed version')
    key = Path('/etc/apt/keyrings/geseidl-nginx.gpg')
    source = Path('/etc/apt/sources.list.d/geseidl-nginx.sources')
    preference = Path('/etc/apt/preferences.d/geseidl-nginx')
    targets = {key: (work / 'nginx.gpg').read_bytes(),
        source: ('Types: deb\nURIs: ' + REPOSITORY + '\nSuites: noble\nComponents: nginx\n'
                 'Architectures: amd64\nSigned-By: ' + str(key) + '\n').encode(),
        preference: ('Package: nginx\nPin: origin nginx.org\nPin-Priority: 600\n\n'
                     'Package: *\nPin: origin nginx.org\nPin-Priority: -1\n').encode()}
    for path, content in targets.items():
        if path.exists() and path.read_bytes() != content:
            raise ValueError('Conflicting existing channel file')
    for path, content in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o644)
    print(json.dumps({'channel_enabled': True, 'scope': 'nginx', 'services_changed': False}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--enable-channel', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    if args.enable_channel:
        enable(args.work, args.version)
    else:
        stage(args.work, args.version)
