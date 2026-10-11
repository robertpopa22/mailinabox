#!/usr/bin/env python3
"""Reproducible edition antispam configuration, opt-in via private site profile.

Default is plan-only. --root stages an offline filesystem clone. Live --apply
backs up only changed files, validates Rspamd and rolls back on failure. Neither
mode trains Bayes, scans mailboxes, sends mail nor installs an AI model.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit

HERE=Path(__file__).resolve().parent
PROFILE=Path('/etc/mailinabox-geseidl-antispam.json')


def read(root,path):
    p=root/path.lstrip('/')
    return p.read_text(encoding='utf-8') if p.exists() else ''


def positive(value,name,minimum,maximum):
    if type(value) is not int or not minimum<=value<=maximum:
        raise ValueError('Invalid '+name)
    return value


def render_gpt(ai):
    url=urlsplit(ai['url'])
    if url.scheme!='http' or url.hostname not in ('127.0.0.1','::1','localhost') or url.username or url.password or url.query or url.fragment:
        raise ValueError('AI endpoint must be an explicitly configured local loopback service')
    if not re.fullmatch(r'[a-zA-Z0-9_.:/-]{1,160}',ai['model']): raise ValueError('Invalid model identifier')
    tokens={
        'URL':json.dumps(ai['url']),'MODEL':json.dumps(ai['model']),
        'INPUT':positive(ai.get('max_input',500),'max_input',100,2000),
        'OUTPUT':positive(ai.get('max_output',72),'max_output',32,256),
        'CONTEXT':positive(ai.get('context',32768),'context',2048,65536),
        'TIMEOUT':positive(ai.get('timeout',90),'timeout',5,150),
    }
    text=(HERE/'gpt.conf.in').read_text(encoding='utf-8')
    for key,value in tokens.items(): text=text.replace('@@'+key+'@@',str(value))
    return text


def build(profile,root=Path('/')):
    if profile.get('enabled') is not True: raise ValueError('Explicit enabled=true required')
    ai=profile['ai']
    timeout=positive(ai.get('task_timeout',120),'task_timeout',30,240)
    if timeout<ai.get('timeout',90)+30: raise ValueError('Task budget needs at least 30 seconds beyond AI')
    files={'/etc/rspamd/override.d/gpt.conf':render_gpt(ai)}
    source=(HERE/'brand_guard.lua').read_text(encoding='utf-8')
    assert source.endswith('return M\n')
    files['/etc/rspamd/plugins.d/geseidl_brand_guard.lua']=source[:-len('return M\n')]+'M.install(rspamd_config)\n'
    options=read(root,'/etc/rspamd/override.d/options.inc')
    if len(re.findall(r'(?m)^\s*task_timeout\s*=',options))>1: raise ValueError('Ambiguous task timeout')
    if re.search(r'(?m)^\s*task_timeout\s*=',options):
        options=re.sub(r'(?m)^[ \t]*task_timeout\s*=[^;]+;',f'task_timeout = {timeout}s;',options)
    else: options+=f'\ntask_timeout = {timeout}s;\n'
    files['/etc/rspamd/override.d/options.inc']=options
    cfg=read(root,'/etc/rspamd/rspamd.conf.local')
    if 'geseidl_brand_guard' not in cfg: cfg+='\ngeseidl_brand_guard { enabled = true; }\n'
    elif not re.search(r'geseidl_brand_guard\s*\{\s*enabled\s*=\s*true\s*;',cfg):
        raise ValueError('Conflicting identity module configuration')
    files['/etc/rspamd/rspamd.conf.local']=cfg
    settings=read(root,'/etc/rspamd/local.d/settings.conf')
    if 'gpt_skip_authenticated' not in settings:
        settings+='\ngpt_skip_authenticated { priority = high; authenticated = yes; apply { symbols_disabled = ["GPT_CHECK"]; } }\n'
    files['/etc/rspamd/local.d/settings.conf']=settings
    composite=read(root,'/etc/rspamd/override.d/composites.conf')
    for name,display,whitelist,score in (
        ('BRAND_IMPERSONATION','BRAND_DISPLAY_MATCH','WHITELIST_BRAND_DOMAIN',7),
        ('COURIER_IMPERSONATION','COURIER_IMPERSONATION_DISPLAY','WHITELIST_COURIER_DOMAIN',5)):
        text=f'{name} {{\n expression = "{display} & !{whitelist} & !LOCAL_OUTBOUND & !BRAND_SENSITIVE_MISMATCH & !BRAND_CONFUSABLE_MISMATCH";\n score = {score}.0;\n}}'
        pattern=r'(?m)^'+name+r'\s*\{[^{}]*\}'
        if re.search(pattern,composite): composite=re.sub(pattern,lambda _:text,composite)
        else: composite+='\n'+text+'\n'
    files['/etc/rspamd/override.d/composites.conf']=composite
    # Keep the rest of the site's scoring and authentication policy intact.
    groups=read(root,'/etc/rspamd/local.d/groups.conf')
    missing=[]
    for symbol,weight in [('GPT_SPAM',4),('GPT_HAM',-2),('GPT_PHISHING',1),('GPT_SCAM',1),('GPT_MALWARE',1)]:
        pattern=r'("'+symbol+r'"\s*\{\s*weight\s*=\s*)[^;]+'
        count=len(re.findall(pattern,groups))
        if count>1: raise ValueError('Duplicate AI weight: '+symbol)
        if count: groups=re.sub(pattern,lambda m:m[1]+str(weight)+'.0',groups)
        else: missing.append('"'+symbol+'" { weight = '+str(weight)+'.0; }')
    if missing: groups+='\ngroup "GPT" { symbols { '+' '.join(missing)+' } }\n'
    files['/etc/rspamd/local.d/groups.conf']=groups
    previous_sa=read(root,'/etc/rspamd/local.d/spamassassin.conf')
    if previous_sa.strip() and '/var/lib/rspamd/geseidl-sa/current.cf' not in previous_sa:
        raise ValueError('Existing non-edition SpamAssassin import requires explicit merge')
    files['/etc/rspamd/local.d/spamassassin.conf']='''# Audited signed subset, scoring in the identity module.
ruleset = "/var/lib/rspamd/geseidl-sa/current.cf";
match_limit = 16000;
alpha = 0.0;
scores_priority = 0;
'''
    files['/usr/local/sbin/geseidl-antispam-rule-update']=(HERE/'antispam_rule_update.py').read_text(encoding='utf-8')
    files['/usr/local/bin/rspamd_learn_report.py']=(HERE/'rspamd_report.py').read_text(encoding='utf-8')
    files['/usr/local/lib/geseidl-antispam/reputation_dns.py']=(HERE.parent/'dns/reputation_dns.py').read_text(encoding='utf-8')
    for name in ('geseidl-antispam-update.service','geseidl-antispam-update.timer'):
        files['/etc/systemd/system/'+name]=(HERE/name).read_text(encoding='utf-8')
    return files


def command(args):
    return subprocess.check_output(args,text=True,stderr=subprocess.PIPE,timeout=180)


def apply(profile,root=Path('/'),commit=False,reload=True,validator=None):
    files=build(profile,root)
    changed={root/name.lstrip('/'):text for name,text in files.items() if read(root,name)!=text}
    result=dict(changed=[str(p) for p in changed],mode='plan')
    if not commit: return result
    live=root.resolve()==Path('/')
    if live and not Path('/var/lib/rspamd/geseidl-sa/current.cf').is_file():
        raise ValueError('Bootstrap the signed subset with antispam_rule_update.py --bootstrap first')
    backup=Path(tempfile.mkdtemp(prefix='geseidl-antispam-',dir='/var/backups' if live else root))
    originals={}
    for p in changed:
        if p.exists():
            saved=backup/p.relative_to(root);saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,saved)
            originals[str(p)]={'exists':True,'uid':p.stat().st_uid,'gid':p.stat().st_gid,'mode':p.stat().st_mode & 0o777}
        else: originals[str(p)]={'exists':False}
    (backup/'manifest.json').write_text(json.dumps(originals,indent=2))
    try:
        for p,text in changed.items():
            p.parent.mkdir(parents=True,exist_ok=True)
            temporary=p.with_name(p.name+'.geseidl-new');temporary.write_text(text,encoding='utf-8',newline='\n')
            mode=0o755 if '/usr/local/' in str(p) else 0o644
            if p.exists(): mode=p.stat().st_mode & 0o777
            temporary.chmod(mode)
            if live and p.exists(): os.chown(temporary,p.stat().st_uid,p.stat().st_gid)
            os.replace(temporary,p)
        if validator is not None: validator(root)
        if live:
            command(['rspamadm','configtest'])
            command(['systemctl','daemon-reload'])
            if reload and changed: command(['systemctl','reload','rspamd'])
            command(['systemctl','enable','--now','geseidl-antispam-update.timer'])
        result.update(mode='applied',backup=str(backup),hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in changed})
        (backup/'result.json').write_text(json.dumps(result,indent=2))
        return result
    except Exception:
        for name,meta in originals.items():
            p=Path(name)
            if meta['exists']:
                shutil.copy2(backup/p.relative_to(root),p)
                if live: os.chown(p,meta['uid'],meta['gid'])
            else: p.unlink(missing_ok=True)
        if live:
            command(['systemctl','daemon-reload'])
            command(['rspamadm','configtest'])
            if reload: command(['systemctl','reload','rspamd'])
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',type=Path,default=PROFILE)
    parser.add_argument('--root',type=Path,default=Path('/'))
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--no-reload',action='store_true')
    args=parser.parse_args()
    if not args.profile.is_file():
        print('SKIP: no private antispam profile; no deployment defaults guessed')
    else:
        profile=json.loads(args.profile.read_text())
        print(json.dumps(apply(profile,args.root,args.apply,not args.no_reload),indent=2))
