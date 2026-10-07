import importlib.util
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'setup/geseidl_edition/components/dovecot24.py'
spec = importlib.util.spec_from_file_location('dovecot24', SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

CONFIG = '''auth_mechanisms = plain login
mail_location = maildir:/srv/mail/%d/%n
protocols = " imap lmtp sieve pop3"
ssl = required
ssl_key = # hidden
ssl_cert = </srv/tls/certificate.pem
auth_policy_hash_nonce = # hidden
auth_policy_request_attributes = request.username=%u request.remote=%r
passdb {
  args = /etc/dovecot/auth-sql.conf.ext
  driver = sql
}
userdb {
  args = /etc/dovecot/auth-sql.conf.ext
  driver = sql
}
plugin {
  quota = maildir
  quota_grace = 10%%
  sieve = /srv/sieve/%d/%n.sieve
  sieve_dir = /srv/sieve/%d/%n
  sieve_max_redirects = 0
  imapsieve_mailbox1_name = Spam
  imapsieve_mailbox1_causes = COPY APPEND
  imapsieve_mailbox1_before = file:/etc/dovecot/sieve/spam.sieve
  imapsieve_mailbox2_name = *
  imapsieve_mailbox2_from = Spam
  imapsieve_mailbox2_causes = COPY
  imapsieve_mailbox2_before = file:/etc/dovecot/sieve/ham.sieve
}
namespace inbox {
  inbox = yes
  location =
  prefix =
}
'''
SQL = {'driver': 'sqlite', 'connect': '/srv/users.sqlite', 'default_pass_scheme': 'SHA512-CRYPT',
    'password_query': "SELECT u.email AS user, u.password, r.allow_nets FROM users u LEFT JOIN restrictions r ON r.email=u.email WHERE u.email='%u';",
    'user_query': "SELECT email AS user, 'mail' AS uid, 'mail' AS gid, '/srv/mail/%d/%n' AS home, '*:bytes=' || quota AS quota_rule FROM users WHERE email='%u';",
    'iterate_query': 'SELECT email AS user FROM users;'}
PRIVATE = {'sql_path': '/etc/dovecot/auth-sql.conf.ext', 'ssl_key': '</srv/tls/key.pem',
    'auth_policy_hash_nonce': 'fixture-nonce', 'auth_policy_request_attributes': 'request.username=%u request.remote=%{rip} request.protocol=%s'}


def test_preserves_authentication_network_policy_quotas_and_storage_recovery():
    output = module.convert(CONFIG, SQL, PRIVATE)
    assert 'dovecot_storage_version = 2.3.21' in output
    assert 'dovecot_config_version = 2.4.5' in output
    assert 'sieve_max_cpu_time = 30s' in output
    assert 'request.remote = "%{remote_ip}"' in output
    assert 'request.protocol = "%{protocol}"' in output
    assert 'delivery = "no"' in output
    assert "r.allow_nets FROM users u LEFT JOIN restrictions r ON r.email=u.email WHERE u.email='%{user}';" in output
    assert "quota || 'B' AS quota_storage_size" in output
    assert "CAST(quota / 10 AS INTEGER) || 'B' AS quota_storage_grace" in output
    assert 'ssl = "required"' in output
    assert 'local 127.0.0.1 {' in output and 'auth_allow_cleartext = "yes"' in output
    assert 'sieve_max_redirects = "0"' in output
    assert 'imapsieve_from "Spam" {' in output
    assert 'sieve_script learn1 {' in output and 'append = "yes"' in output
    assert 'mail_path = "/srv/mail/%{user | domain}/%{user | username}"' in output


@pytest.mark.parametrize('change', [
    CONFIG + 'disable_plaintext_auth = no\n',
    CONFIG.replace('quota_grace = 10%%', 'quota_grace = 50%%'),
    CONFIG.replace('maildir:/srv/mail/%d/%n', 'mdbox:/srv/mail/%d/%n'),
    CONFIG.replace('imapsieve_mailbox2_name = *', 'imapsieve_mailbox2_name = Archive'),
])
def test_requires_review_instead_of_silently_discarding_policy(change):
    with pytest.raises(ValueError):
        module.convert(change, SQL, PRIVATE)
