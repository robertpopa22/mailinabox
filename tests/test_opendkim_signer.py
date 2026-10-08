import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('signer',Path(__file__).resolve().parents[1]/'setup/geseidl_edition/components/opendkim_signer.py')
signer=importlib.util.module_from_spec(spec);spec.loader.exec_module(signer)


def test_roles_preserve_private_tables_and_header_policy():
    original='# comment\nKeyTable refile:/private/keys\nMode sv\nOmitHeaders X-Custom\nAlwaysAddARHeader true\n'
    out=signer.render(original,rspamd=True)
    assert 'KeyTable refile:/private/keys' in out
    assert 'OmitHeaders X-Custom,DKIM-Signature\n' in out
    assert 'Mode s\n' in out and 'AlwaysAddARHeader false\n' in out
    assert signer.render(out,rspamd=True)==out
    fallback=signer.render(out,rspamd=False)
    assert 'Mode sv\n' in fallback and 'AlwaysAddARHeader true\n' in fallback


def test_external_header_map_refused():
    with pytest.raises(ValueError,match='explicit review'):
        signer.render('OmitHeaders refile:/private/headers\n',rspamd=True)
