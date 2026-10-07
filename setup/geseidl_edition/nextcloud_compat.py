#!/usr/bin/env python3
"""Build the edition's IMAP-only authentication app from reviewed upstream 4.0.0.

The upstream app stays intact, including its signature and compatibility ceiling.
Our app has its own ID/namespace/version, preserves existing users_external rows,
and uses the upstream guarded schema migration. Its release is maintained here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

SOURCE_HASHES = {
    'lib/Base.php': '84e8859c3b64ba51cde60a4726e4ee0a3f535035d6433218b1ff668eb6d78358',
    'lib/IMAP.php': '22033e15df6727adb522632af0ab78ae6fa70c474c6b4d0ef6851447bc8325fb',
    'lib/Migration/Version0010Date20200630193751.php': '0d21e903b7674675c89f0d2089cc7e5961196c4ecee299a49d646b9d5f5430fc',
}
APP_ID = 'geseidl_user_external'


def build(source, target_major):
    source = Path(source).resolve(strict=True)
    if target_major not in (34, 35):
        raise ValueError('Only reviewed Nextcloud 34/35 targets are supported')
    info = ET.parse(source / 'appinfo/info.xml').getroot()
    if info.findtext('id') != 'user_external' or info.findtext('version') != '4.0.0':
        raise ValueError('Expected upstream user_external 4.0.0')
    for name, expected in SOURCE_HASHES.items():
        if hashlib.sha256((source / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f'Unreviewed upstream source: {name}')
    target = source.parent / APP_ID
    target.mkdir(exist_ok=True)
    (target / 'appinfo').mkdir(exist_ok=True)
    (target / 'lib/Migration').mkdir(parents=True, exist_ok=True)
    names = list(SOURCE_HASHES)
    for name in names:
        content = (source / name).read_text()
        content = content.replace('OCA\\UserExternal', 'OCA\\GeseidlUserExternal')
        (target / name).write_text(content)
    for name in ['COPYING', 'COPYING-README', 'LICENSE']:
        if (source / name).is_file():
            shutil.copy2(source / name, target / name)
    (target / 'appinfo/info.xml').write_text('''<?xml version="1.0"?>
<info>
  <id>geseidl_user_external</id>
  <name>Geseidl IMAP authentication</name>
  <summary>Edition-maintained IMAP authentication with preserved external user identities</summary>
  <description>Derived from reviewed user_external 4.0.0 Base, IMAP and guarded schema migration. The edition maintains compatibility and tests authentication and DAV before deployment.</description>
  <version>1.0.0</version><licence>agpl</licence>
  <author>Geseidl IT Solutions; upstream user_external authors</author>
  <namespace>GeseidlUserExternal</namespace>
  <types><prelogin/><authentication/></types>
  <category>integration</category>
  <dependencies><nextcloud min-version="34" max-version="35"/></dependencies>
</info>
''')
    (target / 'provenance.json').write_text(json.dumps({
        'base_release': 'user_external 4.0.0', 'source_hashes': SOURCE_HASHES,
        'edition_version': '1.0.0', 'namespace': 'GeseidlUserExternal',
        'database_table': 'users_external', 'scope': 'IMAP only',
    }, indent=2))
    return target


def configure(config, php):
    # Preserve all arguments, user identities and unrelated config. Never emit it.
    code = '''include $argv[1];
foreach ($CONFIG['user_backends'] as &$backend) {
    $class = ltrim($backend['class'], chr(92));
    if ($class === 'OCA\\UserExternal\\IMAP') {
        $backend['class'] = 'OCA\\GeseidlUserExternal\\IMAP';
    } elseif ($class !== 'OCA\\GeseidlUserExternal\\IMAP') {
        fwrite(STDERR, "Unreviewed external authentication backend\\n"); exit(1);
    }
}
unset($backend);
file_put_contents($argv[1], '<?php'.chr(10).'$'.'CONFIG = '.var_export($CONFIG, true).';'.chr(10));
'''
    subprocess.run([php, '-r', code, str(config)], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', required=True)
    parser.add_argument('--target-major', required=True, type=int)
    parser.add_argument('--config')
    parser.add_argument('--php', default='php')
    args = parser.parse_args()
    print(build(args.app, args.target_major))
    if args.config:
        configure(args.config, args.php)
