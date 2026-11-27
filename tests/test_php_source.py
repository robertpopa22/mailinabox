import re
from pathlib import Path

SYSTEM = (Path(__file__).parents[1] / 'setup/system.sh').read_text(encoding='utf-8')
SURY_KEY_FPR = '15058500A0235D97F5D10063B188E2B695BD4743'


def test_frozen_ppa_is_only_a_bootstrap_for_the_sury_repository():
    block = re.search(r'if ! dpkg -s debsuryorg-repository-php.*?\n\s*fi\s*\n', SYSTEM, re.S).group(0)
    assert 'add-apt-repository -y ppa:ondrej/php' in block
    assert 'apt_install debsuryorg-repository-php' in block
    outside = SYSTEM.replace(block, '')
    assert not re.search(r'add-apt-repository\s+-+y\s+ppa:ondrej/php', outside)


def test_sury_key_is_pinned_and_the_ppa_is_removed():
    assert f'SURY_KEY_FPR={SURY_KEY_FPR}' in SYSTEM
    assert 'Signed-By' in SYSTEM and 'gpg --show-keys --with-colons "$SURY_KEYRING"' in SYSTEM and 'exit 1' in SYSTEM
    assert 'deb.sury.org-php.gpg' not in SYSTEM
    assert 'rm -f /etc/apt/sources.list.d/ondrej-ubuntu-php-*.sources' in SYSTEM


def _bash():
    # On Windows the PATH bash is often the WSL launcher, which drops the environment.
    import os, shutil
    git_bash = Path(r'C:\Program Files\Git\bin\bash.exe')
    return str(git_bash) if os.name == 'nt' and git_bash.exists() else shutil.which('bash')


def _keyring_check(tmp_path, sources_text, keys_text):
    import subprocess
    block = re.search(r'SURY_KEYRING=\$\(.*?\nfi\n', SYSTEM, re.S).group(0)
    (tmp_path / 'php.sources').write_bytes(sources_text.encode())
    fake_gpg = 'gpg() { printf %s "$KEYS"; }\n'
    script = ('set -euo pipefail\n' + f'SURY_KEY_FPR={SURY_KEY_FPR}\n' + fake_gpg
              + block.replace('/etc/apt/sources.list.d/', './') + 'echo "OK $SURY_KEYRING"\n')
    return subprocess.run([_bash(), '-s'], input=script.encode(), capture_output=True, cwd=tmp_path.resolve(),
                          env={**__import__('os').environ, 'KEYS': keys_text})


def test_sury_keyring_check_runs_under_pipefail(tmp_path):
    if not _bash():
        import pytest
        pytest.skip('bash required')
    src = 'Types: deb\nURIs: https://packages.sury.org/php/\nSigned-By: /usr/share/keyrings/debsuryorg-archive-keyring.gpg\n'
    good = _keyring_check(tmp_path, src, f'fpr:::::::::{SURY_KEY_FPR}:\n')
    assert good.returncode == 0 and b'OK /usr/share/keyrings/debsuryorg-archive-keyring.gpg' in good.stdout
    bad = _keyring_check(tmp_path, src, 'fpr:::::::::0000000000000000000000000000000000000000:\n')
    assert bad.returncode == 1
    missing = _keyring_check(tmp_path, 'Types: deb\n', f'fpr:::::::::{SURY_KEY_FPR}:\n')
    assert missing.returncode == 1
