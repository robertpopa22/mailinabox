"""Limit Ubuntu OpenDKIM to signing when Rspamd supplies verification.

This is a role mitigation, not a package CVE patch. The native skip-header
option also excludes attacker-provided DKIM-Signature tags while signing.
"""
import argparse
from pathlib import Path
import re


def render(text, *, rspamd):
    settings={'Mode':'s' if rspamd else 'sv',
              'AlwaysAddARHeader':'false' if rspamd else 'true',
              'KeepAuthResults':'true' if rspamd else 'false'}
    omit=[]
    if rspamd:
        for line in text.splitlines():
            m=re.match(r'^\s*OmitHeaders\s+(.+?)\s*(?:#.*)?$',line,re.I)
            if m:
                value=m.group(1)
                if ':' in value:
                    raise ValueError('External OmitHeaders map requires explicit review')
                omit += [v.strip() for v in value.split(',') if v.strip()]
        if 'dkim-signature' not in {s.lower() for s in omit}:
            omit.append('DKIM-Signature')
        settings['OmitHeaders']=','.join(omit)
    keys={k.lower() for k in settings}
    lines=[line for line in text.splitlines()
           if not re.match(r'^\s*(?:'+'|'.join(keys)+r')\s+',line,re.I)]
    lines.extend(k+' '+v for k,v in settings.items())
    return '\n'.join(lines)+'\n'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=Path('/etc/opendkim.conf'))
    p.add_argument('--rspamd',action='store_true')
    p.add_argument('--spam-filter',choices=['','rspamd','spamassassin'])
    p.add_argument('--apply',action='store_true')
    a=p.parse_args()
    if a.config.is_symlink():
        raise ValueError('Refuse configuration symlink')
    before=a.config.read_text()
    rspamd=a.rspamd or a.spam_filter=='rspamd'
    after=render(before,rspamd=rspamd)
    if a.apply:
        a.config.write_text(after)
    print('changed='+str(before!=after).lower()+'; role='+('signer' if rspamd else 'signer+verifier'))


if __name__=='__main__':
    main()
