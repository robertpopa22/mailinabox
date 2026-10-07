import pytest
from management.geseidl_edition.php_runtime import php_fpm_service


def test_existing_deployments_keep_their_backup_runtime_until_cutover():
    assert php_fpm_service({}) == 'php8.3-fpm'
    assert php_fpm_service({'MIAB_PHP_SERVICE': 'php8.5-fpm'}) == 'php8.5-fpm'


@pytest.mark.parametrize('value', ['', 'php8.5-fpm;reboot', '../php8.5-fpm', 'nginx'])
def test_invalid_service_marker_cannot_become_a_service_command(value):
    with pytest.raises(ValueError):
        php_fpm_service({'MIAB_PHP_SERVICE': value})
