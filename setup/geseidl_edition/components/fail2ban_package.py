#!/usr/bin/env python3
"""Stage one reviewed stable Fail2ban publisher asset without installing it."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Mail-in-a-Box-release-review'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def stage(work, tag, asset_name, version):
    if '/' in tag or '/' in asset_name or '\\' in asset_name or not asset_name.endswith('_all.deb'):
        raise ValueError('Expected a release tag and architecture-independent Debian asset')
    work.mkdir(mode=0o700, parents=True, exist_ok=False)
    release_bytes = fetch('https://api.github.com/repos/fail2ban/fail2ban/releases/tags/' + tag)
    release = json.loads(release_bytes)
    (work / 'release.json').write_bytes(release_bytes)
    if release['prerelease'] or release['draft'] or release['tag_name'] != tag:
        raise ValueError('Expected the reviewed stable publisher release')
    assets = [item for item in release['assets'] if item['name'] == asset_name]
    if len(assets) != 1:
        raise ValueError('Reviewed publisher asset missing or ambiguous')
    asset = assets[0]
    expected = asset.get('digest', '')
    if not expected.startswith('sha256:') or len(expected) != 71:
        raise ValueError('Publisher asset checksum unavailable')
    url = asset['browser_download_url']
    if not url.startswith('https://github.com/fail2ban/fail2ban/releases/download/' + tag + '/'):
        raise ValueError('Unexpected publisher asset URL')
    content = fetch(url)
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected[7:]:
        raise ValueError('Publisher asset checksum mismatch')
    target = work / asset_name
    target.write_bytes(content)
    for field, required in [('Package', 'fail2ban'), ('Version', version), ('Architecture', 'all')]:
        actual = subprocess.check_output(['dpkg-deb', '-f', str(target), field], text=True).strip()
        if actual != required:
            raise ValueError('Unexpected Debian package ' + field)
    manifest = {'verified_at': datetime.now(timezone.utc).isoformat(), 'release': release['html_url'],
        'tag': tag, 'asset': asset_name, 'version': version, 'sha256': digest,
        'published_at': release['published_at'], 'verification': 'publisher HTTPS and API asset SHA256',
        'pgp_signature_verified': False, 'package_installed': False}
    (work / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--asset', required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    print(json.dumps(stage(args.work, args.tag, args.asset, args.version)))
