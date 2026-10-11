import importlib.util
from pathlib import Path
import pytest

ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('antispam',ROOT/'setup/geseidl_edition/zones/spam/antispam.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def profile():
    return {'enabled':True,'ai':{'url':'http://127.0.0.1:11434/api/chat','model':'local-approved-model'}}


def test_offline_apply_preserves_custom_policy_and_is_idempotent(tmp_path):
    p=tmp_path/'etc/rspamd/local.d/groups.conf';p.parent.mkdir(parents=True)
    p.write_text('group "other" { symbols { CUSTOM { weight=2; } } }\n')
    result=module.apply(profile(),tmp_path,True)
    assert result['changed']
    assert 'CUSTOM { weight=2; }' in p.read_text()
    assert '"GPT_HAM" { weight = -2.0; }' in p.read_text()
    assert not module.apply(profile(),tmp_path)['changed']
    gpt=(tmp_path/'etc/rspamd/override.d/gpt.conf').read_text()
    assert 'condition =' not in gpt and 'timeout = 90' in gpt
    assert 'max_tokens = 500' in gpt and 'num_predict = 72' in gpt
    assert 'autolearn = false' in gpt and 'allow_ham = false' in gpt
    settings=(tmp_path/'etc/rspamd/local.d/settings.conf').read_text()
    assert 'authenticated = yes' in settings and '"GPT_CHECK"' in settings


@pytest.mark.parametrize('change',[
    {'url':'https://external.example/api'},
    {'url':'http://user:secret@127.0.0.1/api'},
    {'model':'bad"; enabled=false'},
    {'task_timeout':95},{'max_output':4096},
])
def test_invalid_or_external_ai_profile_refused(tmp_path,change):
    settings=profile();settings['ai'].update(change)
    with pytest.raises(ValueError): module.apply(settings,tmp_path,True)
    assert not (tmp_path/'etc').exists()


def test_unrelated_sa_policy_refuses_before_mutation(tmp_path):
    p=tmp_path/'etc/rspamd/local.d/spamassassin.conf';p.parent.mkdir(parents=True)
    p.write_text('ruleset="operator-owned.cf";')
    with pytest.raises(ValueError): module.apply(profile(),tmp_path,True)
    assert p.read_text()=='ruleset="operator-owned.cf";'


def test_setup_calls_edition_and_no_longer_reinstates_obsolete_ai():
    script=(ROOT/'setup/rspamd.sh').read_text()
    assert 'antispam.py --apply --no-reload' in script
    assert 'score >= 4' not in script
    assert 'num_predict = 180' not in script
    assert '"GPT_HAM" { weight = 0.0;' not in script


def test_failed_validation_restores_only_changed_files(tmp_path):
    p=tmp_path/'etc/rspamd/local.d/groups.conf';p.parent.mkdir(parents=True)
    original='group "operator" { symbols { KEEP { weight=1; } } }\n'
    p.write_text(original)
    def reject(root):raise RuntimeError('native configuration validation failed')
    with pytest.raises(RuntimeError):module.apply(profile(),tmp_path,True,validator=reject)
    assert p.read_text()==original
    assert not (tmp_path/'etc/rspamd/override.d/gpt.conf').exists()
