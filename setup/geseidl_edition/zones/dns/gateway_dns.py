#!/usr/bin/env python3
"""Optional UniFi gateway adapter: one identified resolver may do real recursion.

Run ONLY on the gateway with an operator-owned JSON profile (source_ip,
source_mac, interface). No subnet exemptions, ACCEPT rules or chain flushes.
The default prints a plan. --watch maintains exact NAT RETURN rules; stopping
the dedicated service removes only its own rules. Firewall/IPS remain intact.
"""
import argparse
import ipaddress
import json
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

CHAIN='UBIOS_DNSFILTER_JUMP'
TAG='geseidl-reputation-resolver'


def load(path):
    profile=json.loads(Path(path).read_text())
    profile['source_ip']=str(ipaddress.IPv4Address(profile['source_ip']))
    profile['source_mac']=profile['source_mac'].lower()
    if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}',profile['source_mac']):
        raise ValueError('An exact source MAC is required')
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,15}',profile['interface']):
        raise ValueError('An exact LAN interface is required')
    return profile


def rules(profile):
    return [['-i',profile['interface'],'-s',profile['source_ip']+'/32',
             '-p',proto,'--dport','53','-m','mac','--mac-source',profile['source_mac'],
             '-m','comment','--comment',TAG,'-j','RETURN'] for proto in ('tcp','udp')]


def ipt(operation,rule):
    return subprocess.run(['iptables','-w','5','-t','nat',operation,CHAIN]+
        (['1'] if operation=='-I' else [])+rule,capture_output=True,text=True)


def remove(profile):
    for rule in rules(profile):
        while ipt('-C',rule).returncode==0:
            if ipt('-D',rule).returncode: raise RuntimeError('Exact rule removal failed')


def ensure(profile):
    neighbors=json.loads(subprocess.check_output(['ip','-j','neigh','show',profile['source_ip']],text=True))
    if not any(n.get('lladdr','').lower()==profile['source_mac'] and n.get('dev')==profile['interface'] for n in neighbors):
        remove(profile)
        raise RuntimeError('Resolver IP/MAC binding is not confirmed by the gateway')
    for rule in rules(profile):
        if ipt('-C',rule).returncode and ipt('-I',rule).returncode:
            remove(profile)
            raise RuntimeError('Narrow DNS exemption could not be applied')


def watch(profile):
    def stop(*unused): raise SystemExit(0)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        while True:
            ensure(profile)
            time.sleep(15)
    finally: remove(profile)


def install(profile_path):
    """Explicit gateway opt-in, persistent /data assets plus existing udm-boot."""
    profile=load(profile_path)
    subprocess.run(['systemctl','is-enabled','udm-boot.service'],check=True,capture_output=True)
    root=Path('/data/geseidl-reputation-dns');root.mkdir(mode=0o700,exist_ok=True)
    target=root/'gateway_dns.py'
    if Path(__file__).resolve()!=target.resolve(): shutil.copyfile(__file__,target)
    (root/'profile.json').write_text(json.dumps(profile));(root/'profile.json').chmod(0o600)
    unit='''[Unit]
Description=Preserve direct DNS recursion for the identified mail resolver
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
ExecStart=/usr/bin/python3 /data/geseidl-reputation-dns/gateway_dns.py --profile /data/geseidl-reputation-dns/profile.json --watch
ExecStopPost=/usr/bin/python3 /data/geseidl-reputation-dns/gateway_dns.py --profile /data/geseidl-reputation-dns/profile.json --remove
Restart=on-failure
RestartSec=15
[Install]
WantedBy=multi-user.target
'''
    (root/'service.unit').write_text(unit)
    boot=Path('/data/on_boot.d/20-geseidl-reputation-dns.sh')
    boot.write_text('''#!/bin/sh
set -eu
install -m 644 /data/geseidl-reputation-dns/service.unit /etc/systemd/system/geseidl-reputation-dns.service
systemctl daemon-reload
systemctl enable --now geseidl-reputation-dns.service
''');boot.chmod(0o755)
    subprocess.run(['sh',str(boot)],check=True,capture_output=True)
    ensure(profile)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',required=True)
    action=parser.add_mutually_exclusive_group()
    action.add_argument('--apply',action='store_true')
    action.add_argument('--remove',action='store_true')
    action.add_argument('--watch',action='store_true')
    action.add_argument('--install',action='store_true')
    args=parser.parse_args();profile=load(args.profile)
    if args.install: install(args.profile)
    elif args.remove: remove(profile)
    elif args.watch: watch(profile)
    elif args.apply: ensure(profile)
    else: print(json.dumps({'table':'nat','chain':CHAIN,'rules':rules(profile)}))
