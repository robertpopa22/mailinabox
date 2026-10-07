#!/usr/bin/env python3
"""Persist the runtime selected by provisioning for subsequent coherent backups."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--version', required=True)
parser.add_argument('--zpush-cli-only', action='store_true')
args = parser.parse_args()
if not re.fullmatch(r'\d+\.\d+', args.version):
    parser.error('Expected a numeric PHP major.minor')
if not shutil.which('php' + args.version):
    raise SystemExit('Selected PHP executable unavailable')
if Path('/usr/local/lib/z-push/version').exists():
    targets = []
    for name in ['admin', 'top']:
        path = Path('/usr/sbin/z-push-' + name)
        if path.exists() or path.is_symlink():
            expected = r'#!/bin/bash\s+php\d+\.\d+ /usr/local/lib/z-push/z-push-' + name + r'\.php "\$@"\s*'
            if path.is_symlink() or not re.fullmatch(expected, path.read_text()):
                raise SystemExit('Unrecognised Z-Push wrapper; refusing to overwrite')
        targets.append((path, name))
    for path, name in targets:
        content = '#!/bin/bash\nphp' + args.version + ' /usr/local/lib/z-push/z-push-' + name + '.php "$@"\n'
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False, mode='w') as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
            temporary = Path(out.name)
        os.chmod(temporary, 0o755)
        os.replace(temporary, path)
if not args.zpush_cli_only:
    subprocess.run([sys.executable, 'tools/editconf.py', '/etc/mailinabox.conf',
                    'MIAB_PHP_SERVICE=php' + args.version + '-fpm'], check=True)
