#!/usr/bin/env python3
"""Configure OPcache independently of a distribution's extension-loader ini path."""
import argparse
import os
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--version', required=True)
args = parser.parse_args()
if not re.fullmatch(r'\d+\.\d+', args.version):
    parser.error('Expected numeric PHP major.minor')
subprocess.run(['php' + args.version, '-r',
    "exit(function_exists('opcache_get_status') ? 0 : 1);"], check=True)
base = Path('/etc/php') / args.version
target = base / 'mods-available/mailinabox-opcache.ini'
target.write_text('''; Mail-in-a-Box OPcache settings; independent of extension loading.
opcache.enable=1
opcache.enable_cli=1
opcache.interned_strings_buffer=8
opcache.max_accelerated_files=10000
opcache.memory_consumption=128
opcache.revalidate_freq=1
''')
os.chmod(target, 0o644)
for sapi in ['cli', 'fpm']:
    link = base / sapi / 'conf.d/99-mailinabox-opcache.ini'
    if link.is_symlink():
        if link.resolve() != target.resolve():
            raise SystemExit('Unexpected OPcache configuration link')
    elif link.exists():
        raise SystemExit('Unexpected OPcache configuration file')
    else:
        link.symlink_to(target)
