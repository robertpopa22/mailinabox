#!/usr/bin/env python3
"""Direct recursion for reputation zones; plan, verify, atomic apply and rollback.

Public resolvers aggregate users and can be refused by URIBL/DNSWL. Keep normal
forwarding and existing Spamhaus/DQS configuration untouched. Never turn a
refused positive canary into a successful negative lookup.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ZONES = ('uribl.com', 'dnswl.org')
FILENAME = 'geseidl-reputation-zones.conf'
INCLUDE = 'include "/etc/bind/' + FILENAME + '";'


def render():
    return '# Geseidl Edition: reputation queries require a private recursive resolver.\n' + ''.join(
        'zone "' + zone + '" { type forward; forward first; forwarders { }; };\n' for zone in ZONES)


def command(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=35)


def probe(server='127.0.0.1', port=53):
    cases = (
        ('uribl-positive', '2.0.0.127.multi.uribl.com', 'A', 'NOERROR', {'127.0.0.14'}),
        ('dnswl-positive', '2.0.0.127.list.dnswl.org', 'A', 'NOERROR', {'127.0.10.0'}),
        ('uribl-negative', 'not-listed.invalid.multi.uribl.com', 'A', 'NXDOMAIN', set()),
        ('dnswl-negative', '1.0.0.127.list.dnswl.org', 'A', 'NXDOMAIN', set()),
        ('ordinary-dns', 'example.com', 'A', 'NOERROR', None),
        ('mail-dns', 'gmail.com', 'MX', 'NOERROR', None),
    )
    results = []
    for name, query, kind, expected_status, expected_answers in cases:
        try:
            raw = command(['dig', '@'+server, '-p', str(port), query, kind,
                           '+time=4', '+tries=2', '+noall', '+answer', '+comments'])
            match = re.search(r'status: (\w+)', raw)
            status = match[1] if match else 'UNKNOWN'
            answers = set(re.findall(r'\sIN\s+'+kind+r'\s+([^\n]+)', raw))
            ok = status == expected_status and (bool(answers) if expected_answers is None else answers == expected_answers)
            results.append(dict(case=name, status=status, answers=sorted(answers), ok=ok))
        except (subprocess.SubprocessError, OSError):
            results.append(dict(case=name, status='UNKNOWN', answers=[], ok=False))
    return dict(status='OK' if all(x['ok'] for x in results) else 'ERROR',
                checked_at=datetime.now(timezone.utc).isoformat(), probes=results)


def plan(directory, effective):
    local = directory/'named.conf.local'
    current = local.read_text()
    owned = directory/FILENAME
    occurrences = current.count(INCLUDE)
    if occurrences > 1:
        raise ValueError('Duplicate reputation include')
    if owned.exists() and owned.read_text() != render():
        raise ValueError('Operator-modified reputation zones require review')
    for zone in ZONES:
        count = len(re.findall(r'\bzone\s+"'+re.escape(zone)+r'"', effective))
        if count != occurrences:
            raise ValueError('Existing/conflicting zone requires review: '+zone)
    return {owned:render(), local:current if occurrences else current+'\n'+INCLUDE+'\n'}


def apply(directory=Path('/etc/bind'), commit=False):
    effective = command(['named-checkconf', '-p'])  # Never print: may contain keys.
    files = plan(directory, effective)
    changed = [p for p, text in files.items() if not p.exists() or p.read_text() != text]
    if not commit:
        return dict(mode='plan', changed=[str(p) for p in changed], zones=ZONES)
    if not changed:
        return dict(changed=False, health=probe())
    backup = Path(tempfile.mkdtemp(prefix='geseidl-reputation-', dir='/var/backups'))
    originals = {}
    for p in changed:
        originals[p] = p.exists()
        if p.exists(): shutil.copy2(p, backup/p.name)
    (backup/'manifest.json').write_text(json.dumps({str(p):exists for p,exists in originals.items()}))
    try:
        for p in changed:
            temporary = p.with_name(p.name+'.geseidl-new')
            temporary.write_text(files[p]); temporary.chmod(0o644)
            if p.exists(): os.chown(temporary,p.stat().st_uid,p.stat().st_gid)
            os.replace(temporary,p)
        command(['named-checkconf'])
        command(['rndc', 'reconfig'])
        for zone in ZONES: command(['rndc', 'flushtree', zone])
        health = probe()
        if health['status'] != 'OK': raise RuntimeError('Reputation/base DNS canary failed')
        return dict(changed=True, backup=str(backup), health=health)
    except Exception:
        for p, existed in originals.items():
            if existed: shutil.copy2(backup/p.name, p)
            else: p.unlink(missing_ok=True)
        command(['named-checkconf'])
        command(['rndc', 'reconfig'])
        for zone in ZONES: command(['rndc', 'flushtree', zone])
        raise


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--verify',action='store_true')
    args=parser.parse_args()
    result=probe() if args.verify else apply(commit=args.apply)
    print(json.dumps(result,indent=2))
    if result.get('status',result.get('health',{}).get('status')) == 'ERROR': raise SystemExit(1)
