#!/usr/bin/env python3
"""Persist the runtime selected by provisioning for subsequent coherent backups."""
import argparse
import re
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--version', required=True)
args = parser.parse_args()
if not re.fullmatch(r'\d+\.\d+', args.version):
    parser.error('Expected a numeric PHP major.minor')
subprocess.run([sys.executable, 'tools/editconf.py', '/etc/mailinabox.conf',
                'MIAB_PHP_SERVICE=php' + args.version + '-fpm'], check=True)
