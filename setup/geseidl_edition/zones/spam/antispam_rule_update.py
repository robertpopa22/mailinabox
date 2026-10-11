#!/usr/bin/env python3
"""Signed SA subset -> native Rspamd, gated publication with last-good rollback.

Only 12 audited body regex atoms are accepted; never plugins, eval, scores,
actions or arbitrary new rules. Native Rspamd owns all overlapping signals.
Run as root from the dedicated systemd service. No email or learning operation.
"""
import argparse, fcntl, hashlib, json, os, pwd, re, shutil, subprocess, time
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

STATE=Path('/var/lib/geseidl-antispam-updates')
ACTIVE=Path('/var/lib/rspamd/geseidl-sa/current.cf')
ATOMS=('ACCESS_SUSPENDED','ACCESS_RESTORE','ACCESS_REVOKE','VERIFY_ACCOUNT',
       'FAILED_LOGINS','ACCOUNT_REACTIV','SECURITY_DEPT','ACCOUNT_ERROR',
       'ACCOUNT_DISRUPT','ACCOUNT_UPGRADE','ACCOUNT_SECURE','SUSPICION_LOGIN')
SYMBOL='GSA_ACCOUNT_PHISHING_CANDIDATE'

def compile_subset(source):
    found={}
    for line in source.splitlines():
        match=re.match(r'^body\s+__(\w+)\s+(.+?)\s*$',line)
        if match and match[1] in ATOMS:
            name,pattern=match.groups()
            if name in found:raise ValueError('duplicate atom '+name)
            if len(pattern)>2048 or not re.fullmatch(r'/[^\n]+/[imsx]*',pattern) or '(?{' in pattern or '(??' in pattern:
                raise ValueError('unsupported regex '+name)
            found[name]=pattern
    if set(found)!=set(ATOMS):raise ValueError('upstream atom missing; hold last-good')
    # Preserve the upstream Apache 2.0 license notice in the generated derivative.
    notice=source.split('# </@LICENSE>',1)[0]
    if '# <@LICENSE>' not in notice:raise ValueError('license notice absent')
    notice+='# </@LICENSE>\n'
    lines=[notice,'# Audited subset; Apache SpamAssassin body patterns, local scoring/dedup.']
    for name in ATOMS:lines.append('body __GSA_'+name+' '+found[name])
    lines += ['meta '+SYMBOL+' ('+' + '.join('__GSA_'+x for x in ATOMS)+') > 3',
              'score '+SYMBOL+' 0.0',
              'describe '+SYMBOL+' Four or more account-phishing phrase families (SA subset)']
    return '\n'.join(lines)+'\n'

def run(args,timeout=45,**kwargs):
    result=subprocess.run(args,capture_output=True,timeout=timeout,**kwargs)
    if result.returncode:raise RuntimeError('command failed: '+str(args[0])+' '+result.stderr.decode(errors='replace')[-1000:])
    return result.stdout

def synthetic_cases():
    return [
        ('attack','Account suspended. To restore access, verify your account information. Security department. Unsuccessful login attempts. Restore your account.',True),
        ('attack2','Your account is incorrect. Upgrade your account. Avoid account suspension. Confirm your billing information. Suspicion login.',True),
        ('invoice','Please verify the invoice. Subscription payment received. Thank you.',False),
        ('security','New sign-in detected. If this was you, no action is needed. Make your account more secure.',False),
        ('welcome','Welcome. Verify your account to finish registration. Thank you.',False),
        ('reset','You requested a password reset. Restore your account with the link you requested.',False),
        ('marketing','Attend our webinar about account security and cloud billing.',False),
        ('ro-invoice','Factura pentru abonamentul lunar este atasata. Va multumim.',False),
    ]

def validate(candidate,lab):
    lab.mkdir(mode=0o750)
    for name in ('modules','tmp','hs'):(lab/name).mkdir()
    shutil.copy2('/usr/share/rspamd/plugins/spamassassin.lua',lab/'modules/spamassassin.lua')
    (lab/'subset.cf').write_text(candidate)
    config='''options { task_timeout=5s; tempdir="%(p)s/tmp"; pidfile="%(p)s/pid"; cache_file="%(p)s/cache"; stats_file="%(p)s/stats"; hs_cache_dir="%(p)s/hs"; control_socket="%(p)s/control"; }
logging { type=file; filename="%(p)s/log"; level=info; }
modules { path="%(p)s/modules"; fallback_path=[]; try_path=[]; }
worker "normal" { bind_socket="%(p)s/socket"; count=1; }
actions { reject=15; add_header=5; }
spamassassin { ruleset="%(p)s/subset.cf"; match_limit=16000; alpha=0.0; scores_priority=0; }
''' % {'p':str(lab)}
    (lab/'rspamd.conf').write_text(config)
    user=pwd.getpwnam('_rspamd')
    for p in [lab,*lab.rglob('*')]:os.chown(p,user.pw_uid,user.pw_gid)
    variables=['--var='+k+'='+str(lab) for k in ('LOCAL_CONFDIR','CONFDIR','DBDIR','RUNDIR','LOGDIR')]
    run(['runuser','-u','_rspamd','--','rspamadm',*variables,'configtest','-c',str(lab/'rspamd.conf')])
    with (lab/'process.log').open('wb') as out:
        proc=subprocess.Popen(['runuser','-u','_rspamd','--','rspamd',*variables,'-f','-c',str(lab/'rspamd.conf')],stdout=out,stderr=out,start_new_session=True)
        try:
            for _ in range(100):
                if (lab/'socket').exists():break
                if proc.poll() is not None:raise RuntimeError('native lab exited')
                time.sleep(.05)
            for label,body,expected in synthetic_cases():
                msg=EmailMessage();msg['From']='Example <sender@example.test>';msg['To']='reader@example.test';msg['Subject']=label;msg.set_content(body)
                response=json.loads(run(['rspamc','-h',str(lab/'socket'),'-t','6','-j'],timeout=8,input=msg.as_bytes()))
                if (SYMBOL in response.get('symbols',{}))!=expected:raise RuntimeError('canary failed: '+label)
        finally:
            import signal
            os.killpg(proc.pid,signal.SIGTERM)
            proc.wait(timeout=10)
    return len(synthetic_cases())

def revision(directory):
    text=(directory/'updates_spamassassin_org.cf').read_text()
    return int(re.search(r'^# UPDATE version (\d+)',text,re.M)[1])

def execute(fetch=True):
    STATE.mkdir(mode=0o755,exist_ok=True)
    lock=(STATE/'lock').open('w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    upstream=STATE/'upstream'
    if not upstream.exists():
        shutil.copytree('/var/lib/spamassassin/4.000002',upstream)
    before=revision(upstream)
    watermark=STATE/'high-water.json'
    floor=max(before,json.loads(watermark.read_text())['revision'] if watermark.exists() else before)
    # Persist before network I/O: a rejected older signed bundle must remain
    # rejected on the next run as well, not become the new comparison baseline.
    watermark.write_text(json.dumps({'revision':floor}))
    if fetch:
        result=subprocess.run(['sa-update','--gpg','--updatedir',str(upstream),'--channel','updates.spamassassin.org'],capture_output=True,timeout=240)
        if result.returncode not in (0,1):raise RuntimeError('signed sa-update failed: '+result.stderr.decode(errors='replace')[-700:])
    serial=revision(upstream)
    if serial<floor:raise RuntimeError('upstream revision rollback refused')
    candidate=compile_subset((upstream/'updates_spamassassin_org/72_active.cf').read_text())
    digest=hashlib.sha256(candidate.encode()).hexdigest()
    if ACTIVE.exists() and hashlib.sha256(ACTIVE.read_bytes()).hexdigest()==digest:
        watermark.write_text(json.dumps({'revision':serial}))
        return dict(status='OK',revision=serial,changed=False,sha256=digest)
    lab=STATE/('test-'+str(time.time_ns()))
    count=validate(candidate,lab)
    ACTIVE.parent.mkdir(mode=0o755,exist_ok=True)
    old=ACTIVE.read_bytes() if ACTIVE.exists() else None
    if old is not None:(STATE/'last-good.cf').write_bytes(old)
    temporary=ACTIVE.with_suffix('.new');temporary.write_text(candidate);os.chmod(temporary,0o644)
    os.replace(temporary,ACTIVE)
    try:
        run(['rspamadm','configtest'])
        run(['systemctl','reload','rspamd'])
        run(['systemctl','is-active','rspamd'])
    except Exception:
        if old is None:ACTIVE.unlink(missing_ok=True)
        else:ACTIVE.write_bytes(old)
        run(['systemctl','reload','rspamd'])
        raise
    watermark.write_text(json.dumps({'revision':serial}))
    return dict(status='OK',revision=serial,changed=True,sha256=digest,canaries=count)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--bootstrap',action='store_true');args=parser.parse_args()
    STATE.mkdir(mode=0o755,exist_ok=True)
    try:
        result=execute(fetch=not args.bootstrap)
    except Exception as exc:
        result={'status':'ERROR','error':str(exc)}
    result['checked_at']=datetime.now(timezone.utc).isoformat()
    temporary=STATE/'status.new';temporary.write_text(json.dumps(result,indent=2));os.replace(temporary,STATE/'status.json')
    labs=sorted((p for p in STATE.iterdir() if re.fullmatch(r'test-\d+',p.name) and p.is_dir() and not p.is_symlink()),key=lambda p:p.name)
    for lab in labs[:-3]:
        if lab.resolve().parent==STATE.resolve():shutil.rmtree(lab)
    print(json.dumps(result))
    if result['status']!='OK':raise SystemExit(1)

if __name__=='__main__':main()
