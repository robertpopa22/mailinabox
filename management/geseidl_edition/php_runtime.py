"""The configured PHP service used for coherent application backups."""
import re


def php_fpm_service(env):
    service = env.get('MIAB_PHP_SERVICE', 'php8.3-fpm')
    if not re.fullmatch(r'php\d+\.\d+-fpm', service):
        raise ValueError('Invalid configured PHP service')
    return service
