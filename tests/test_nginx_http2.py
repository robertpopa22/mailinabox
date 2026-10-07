import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('nginx_http2',
    Path(__file__).resolve().parents[1] / 'setup/geseidl_edition/components/nginx_http2.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_old_version_preserves_configuration():
    text = 'server { listen 443 ssl http2; }\n'
    assert module.adapt(text, '1.24.0') == text


def test_current_version_preserves_unrelated_strings_and_replays():
    text = ('# listen 443 ssl http2;\nserver {\n listen 443 ssl http2;\n'
            ' listen [::]:443 ssl http2;\n set $text "http2; {literal}";\n'
            ' location / { return 200 "${host}"; }\n}\n')
    result = module.adapt(text, '1.30.5')
    assert result.count('http2 on;') == 1
    assert '# listen 443 ssl http2;' in result
    assert '"http2; {literal}"' in result and '"${host}"' in result
    assert 'listen [::]:443 ssl ;' in result
    assert module.adapt(result, '1.30.5') == result


def test_mixed_listener_scope_refused():
    with pytest.raises(ValueError, match='Mixed'):
        module.adapt('server { listen 443 ssl http2; listen 8080; }', '1.30.5')


def test_conflicting_server_policy_refused():
    with pytest.raises(ValueError, match='Conflicting'):
        module.adapt('server { listen 443 ssl http2; http2 off; }', '1.30.5')
