#!/usr/bin/env python3
"""Emit the preserved cipher key to the installer's command substitution only."""
import argparse
from pathlib import Path
import secrets
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config', required=True)
parser.add_argument('--php', required=True)
args = parser.parse_args()
if Path(args.config).exists():
    php = '''include $argv[1]; $key = $config['des_key'] ?? '';
if (strlen($key) < 24 || !preg_match('~^[A-Za-z0-9+/=_-]+$~', $key)) {
    fwrite(STDERR, "Existing cipher key cannot be safely preserved\\n"); exit(1);
}
echo $key;'''
    result = subprocess.run([args.php, '-r', php, args.config], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit('Existing cipher key validation failed')
    print(result.stdout, end='')
else:
    print(secrets.token_urlsafe(32), end='')
