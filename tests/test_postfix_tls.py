import importlib.util
from pathlib import Path

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
