import importlib.util
from pathlib import Path
import sys
import types

SCRIPT=Path(__file__).parents[1]/'setup/geseidl_edition/zones/spam/antispam_rule_update.py'
# Linux-only runner; the compiler itself is platform independent.
if sys.platform=='win32':
    sys.modules.setdefault('fcntl',types.SimpleNamespace())
    sys.modules.setdefault('pwd',types.SimpleNamespace())
spec=importlib.util.spec_from_file_location('antispam_rule_update',SCRIPT)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def source():
    return '# <@LICENSE>\n# Test fixture\n# </@LICENSE>\n'+'\n'.join('body __'+x+' /example/i' for x in module.ATOMS)

def test_only_reviewed_regexes_no_upstream_scores_or_plugins():
    result=module.compile_subset(source()+'\nloadplugin Malicious\nscore __ACCESS_RESTORE 100\nbody UNREVIEWED /free/i')
    assert 'Malicious' not in result and 'UNREVIEWED' not in result and '100' not in result
    assert result.count('body __GSA_')==12
    assert 'score GSA_ACCOUNT_PHISHING_CANDIDATE 0.0' in result

def test_missing_changed_or_duplicate_atom_refuses_update():
    import pytest
    for bad in (source().replace('body __ACCESS_RESTORE','header __ACCESS_RESTORE'),
                source().replace('/example/i','eval:anything()',1),
                source()+'\nbody __ACCESS_RESTORE /duplicate/i'):
        with pytest.raises(ValueError):module.compile_subset(bad)

def prepare_state(tmp_path,monkeypatch):
    state=tmp_path/'state';upstream=state/'upstream';rules=upstream/'updates_spamassassin_org';rules.mkdir(parents=True)
    (upstream/'updates_spamassassin_org.cf').write_text('# UPDATE version 123\n')
    (rules/'72_active.cf').write_text(source())
    active=tmp_path/'current.cf';active.write_text('last good\n')
    monkeypatch.setattr(module,'STATE',state);monkeypatch.setattr(module,'ACTIVE',active)
    if sys.platform=='win32':
        monkeypatch.setattr(module.fcntl,'flock',lambda *a:None,raising=False)
        monkeypatch.setattr(module.fcntl,'LOCK_EX',1,raising=False)
        monkeypatch.setattr(module.fcntl,'LOCK_NB',2,raising=False)
    return active

def test_failed_canary_keeps_last_good(tmp_path,monkeypatch):
    import pytest
    active=prepare_state(tmp_path,monkeypatch)
    def reject(*args):raise RuntimeError('canary failure')
    monkeypatch.setattr(module,'validate',reject)
    with pytest.raises(RuntimeError,match='canary failure'):module.execute(fetch=False)
    assert active.read_text()=='last good\n'

def test_failed_global_configtest_rolls_back_only_rules(tmp_path,monkeypatch):
    import pytest
    active=prepare_state(tmp_path,monkeypatch)
    monkeypatch.setattr(module,'validate',lambda *a:8)
    def command(args):
        if args[0]=='rspamadm':raise RuntimeError('global config failed')
        return b''
    monkeypatch.setattr(module,'run',command)
    with pytest.raises(RuntimeError,match='global config failed'):module.execute(fetch=False)
    assert active.read_text()=='last good\n'

def test_signed_revision_rollback_stays_refused_next_run(tmp_path,monkeypatch):
    import pytest
    active=prepare_state(tmp_path,monkeypatch)
    (module.STATE/'high-water.json').write_text('{"revision":124}')
    for _ in range(2):
        with pytest.raises(RuntimeError,match='rollback refused'):module.execute(fetch=False)
        assert active.read_text()=='last good\n'
