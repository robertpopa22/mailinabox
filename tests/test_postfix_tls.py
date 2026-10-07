import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('postfix_tls',
    Path(__file__).resolve().parents[1] / 'setup/geseidl_edition/components/postfix_tls.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_supported_old_release_keeps_custom_dh():
    config = 'smtpd_tls_dh1024_param_file = /srv/example/dh.pem\nsmtp_tls_security_level = dane\n'
    assert module.cleaned(config, '3.8.6') == config


def test_current_release_removes_only_deprecated_dh():
    config = ('# preserve\nsmtpd_tls_dh1024_param_file =\n /srv/example/dh.pem\n'
              'smtp_tls_security_level = dane\nsmtpd_tls_key_file = /srv/example/key.pem\n')
    expected = '# preserve\nsmtp_tls_security_level = dane\nsmtpd_tls_key_file = /srv/example/key.pem\n'
    assert module.cleaned(config, '3.11.7') == expected
    assert module.cleaned(expected, '3.11.7') == expected


def test_native_metadata_link_becomes_read_only_copy(tmp_path):
    config = tmp_path / 'etc'
    share = tmp_path / 'share'
    config.mkdir()
    share.mkdir()
    source = share / 'makedefs.out'
    source.write_text('native build metadata\n')
    source.chmod(0o644)
    try:
        (config / 'makedefs.out').symlink_to(source)
    except OSError:
        pytest.skip('OS cannot create symlinks')
    assert module.regularize_metadata(config, share)
    assert not (config / 'makedefs.out').is_symlink()
    assert (config / 'makedefs.out').read_bytes() == source.read_bytes()
    assert not module.regularize_metadata(config, share)


def test_unknown_metadata_link_is_preserved_and_refused(tmp_path):
    config = tmp_path / 'etc'
    config.mkdir()
    source = tmp_path / 'custom'
    source.write_text('preserve')
    try:
        (config / 'makedefs.out').symlink_to(source)
    except OSError:
        pytest.skip('OS cannot create symlinks')
    with pytest.raises(ValueError, match='non-native'):
        module.regularize_metadata(config, tmp_path / 'share')
    assert source.read_text() == 'preserve' and (config / 'makedefs.out').is_symlink()
