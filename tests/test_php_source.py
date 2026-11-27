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
    assert 'deb.sury.org-php.gpg' in SYSTEM and 'exit 1' in SYSTEM
    assert 'rm -f /etc/apt/sources.list.d/ondrej-ubuntu-php-*.sources' in SYSTEM
