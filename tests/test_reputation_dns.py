import importlib.util,json,subprocess
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[1]

def load(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/('setup/geseidl_edition/zones/dns/'+name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

dns=load('reputation_dns');gateway=load('gateway_dns')


def test_zone_plan_is_narrow_and_idempotent(tmp_path):
    p=tmp_path/'named.conf.local';p.write_text('include "operator.conf";\n')
    plan=dns.plan(tmp_path,'zone "spamhaus.org" { type forward; };')
    for path,text in plan.items():path.write_text(text)
    assert dns.plan(tmp_path,dns.render())==plan
    assert 'operator.conf' in p.read_text()
    assert 'spamhaus.org' not in dns.render()
    assert dns.render().count('forwarders { };')==2


def test_conflicting_zone_and_owned_edits_refuse(tmp_path):
    (tmp_path/'named.conf.local').write_text('')
    with pytest.raises(ValueError):dns.plan(tmp_path,'zone "uribl.com" { type primary; };')
    (tmp_path/dns.FILENAME).write_text('operator edited')
    with pytest.raises(ValueError):dns.plan(tmp_path,'')


@pytest.mark.parametrize('reply',[
    ';; status: NXDOMAIN\n',
    ';; status: NOERROR\nq 60 IN A 127.0.0.1\n',
    ';; status: NOERROR\nq 60 IN A 127.0.0.255\n',
    ';; status: SERVFAIL\n',
])
def test_negative_or_blocked_positive_canary_is_not_health(monkeypatch,reply):
    monkeypatch.setattr(dns,'command',lambda args:reply)
    assert dns.probe()['status']=='ERROR'


def test_collection_failure_is_unknown(monkeypatch):
    def fail(args):raise subprocess.TimeoutExpired(args,10)
    monkeypatch.setattr(dns,'command',fail)
    result=dns.probe()
    assert result['status']=='ERROR' and all(p['status']=='UNKNOWN' for p in result['probes'])


def test_gateway_rules_require_one_ip_mac_and_never_accept_traffic(tmp_path):
    p=tmp_path/'profile.json';p.write_text(json.dumps({'source_ip':'192.0.2.10','source_mac':'00:11:22:33:44:55','interface':'br0'}))
    profile=gateway.load(p)
    for rule in gateway.rules(profile):
        assert '192.0.2.10/32' in rule and '--mac-source' in rule
        assert rule[-1]=='RETURN' and '53' in rule and 'ACCEPT' not in rule
    p.write_text(json.dumps({**profile,'source_ip':'192.0.2.0/24'}))
    with pytest.raises(ValueError):gateway.load(p)


def test_failed_dns_canary_restores_original_configuration(tmp_path,monkeypatch):
    p=tmp_path/'named.conf.local';p.write_text('include "original.conf";\n')
    backup=tmp_path/'backup';backup.mkdir()
    monkeypatch.setattr(dns.tempfile,'mkdtemp',lambda **kwargs:str(backup))
    monkeypatch.setattr(dns.os,'chown',lambda *args:None,raising=False)
    calls=[]
    def command(args):calls.append(args);return ''
    monkeypatch.setattr(dns,'command',command)
    monkeypatch.setattr(dns,'probe',lambda:{'status':'ERROR'})
    with pytest.raises(RuntimeError):dns.apply(tmp_path,commit=True)
    assert p.read_text()=='include "original.conf";\n'
    assert not (tmp_path/dns.FILENAME).exists()
    assert calls.count(['rndc','reconfig'])==2
