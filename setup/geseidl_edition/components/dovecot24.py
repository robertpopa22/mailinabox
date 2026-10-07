#!/usr/bin/env python3
"""Build a reviewed 2.4 candidate from a 2.3 SQL/Maildir configuration.

Writes only the requested candidate. It does not install packages or alter live
configuration. Unsupported settings fail closed instead of being discarded.
"""
import argparse
import json
from pathlib import Path
import re


def variables(value):
    replacements = {'u': 'user', 'd': 'user | domain', 'n': 'user | username',
        'r': 'remote_ip', 'l': 'local_ip', 's': 'protocol', 'p': 'client_pid',
        'h': 'home', 'w': 'password'}
    value = re.sub(r'%([udnrlsphw])', lambda match: '%{' + replacements[match[1]] + '}', value)
    aliases = {'rip': 'remote_ip', 'lip': 'local_ip', 'rport': 'remote_port',
        'lport': 'local_port', 'service': 'protocol', 'pid': 'process:pid'}
    return re.sub(r'%\{([^}]+)\}', lambda match: '%{' + aliases.get(match[1], match[1]) + '}', value)


def parse(text):
    root = {'name': '', 'settings': {}, 'children': []}
    stack = [root]
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.endswith(' {'):
            node = {'name': line[:-2], 'settings': {}, 'children': []}
            stack[-1]['children'].append(node)
            stack.append(node)
        elif line == '}':
            if len(stack) == 1:
                raise ValueError('Unexpected closing configuration section')
            stack.pop()
        elif '=' in line:
            key, value = (part.strip() for part in line.split('=', 1))
            if key in stack[-1]['settings']:
                raise ValueError('Duplicate setting: ' + key)
            if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
                value = json.loads(value)
            stack[-1]['settings'][key] = value
        else:
            raise ValueError('Unsupported configuration syntax')
    if len(stack) != 1:
        raise ValueError('Unclosed configuration section')
    return root


def convert(text, sql, private, storage_version='2.3.21'):
    if storage_version not in ['2.3.21', '2.4.5']:
        raise ValueError('Unreviewed storage format version')
    if set(sql) != {'driver', 'connect', 'default_pass_scheme', 'password_query', 'user_query', 'iterate_query'}:
        raise ValueError('Unreviewed SQL configuration settings')
    tree = parse(text)
    lines = ['dovecot_config_version = 2.4.5', 'dovecot_storage_version = ' + storage_version,
        'auth_allow_cleartext = no', 'sieve_max_cpu_time = 30s']
    def emit(key, value, depth=0):
        lines.append('  ' * depth + key + ' = ' + json.dumps(variables(value)))
    def begin(name, depth=0):
        lines.append('  ' * depth + name + ' {')
    def end(depth=0):
        lines.append('  ' * depth + '}')
    def boollist(key, value, depth=0):
        begin(key, depth)
        if key == 'cause':
            emit('delivery', 'no', depth + 1)
        for name in value.split():
            if not re.fullmatch(r'[A-Za-z0-9_.;-]+', name):
                raise ValueError('Unsupported list item in ' + key)
            emit(name, 'yes', depth + 1)
        end(depth)
    unchanged = {'auth_mechanisms', 'auth_policy_server_url', 'default_process_limit',
        'default_vsz_limit', 'first_valid_uid', 'imap_idle_notify_interval', 'log_path',
        'login_trusted_networks', 'mail_access_groups', 'mail_privileged_group',
        'postmaster_address', 'ssl', 'ssl_client_ca_dir', 'mail_max_userip_connections',
        'inbox', 'auto', 'special_use', 'prefix', 'mode', 'user', 'group', 'port',
        'process_limit', 'process_min_avail', 'executable', 'client_limit'}
    rename = {'ssl_cipher_list': 'ssl_cipher_list', 'ssl_cert': 'ssl_server_cert_file',
        'ssl_key': 'ssl_server_key_file', 'ssl_dh': 'ssl_server_dh_file',
        'address': 'listen', 'service_count': 'restart_request_count'}
    plugin = next(child for child in tree['children'] if child['name'] == 'plugin')['settings']
    def walk(node, depth=0):
        for key, value in node['settings'].items():
            if key in ['protocols', 'mail_plugins']:
                boollist(key, value, depth)
            elif key == 'mail_location':
                if not value.startswith('maildir:') or ':' in value[len('maildir:'):]:
                    raise ValueError('Only the reviewed plain Maildir layout is supported')
                emit('mail_driver', 'maildir', depth)
                emit('mail_path', value[len('maildir:'):], depth)
            elif key == 'location' and value == '':
                pass  # Empty namespace location inherits the existing Maildir layout.
            elif key == 'auth_policy_hash_nonce':
                emit(key, private[key], depth)
            elif key == 'auth_policy_request_attributes':
                begin(key, depth)
                for item in private[key].split():
                    name, content = item.split('=', 1)
                    emit(name, content, depth + 1)
                end(depth)
            elif key in ['managesieve_notify_capability', 'managesieve_sieve_capability']:
                pass  # Computed by the installed Sieve engine, not administrator policy.
            elif key in rename:
                value = private.get(key, value)
                if key.startswith('ssl_') and value.startswith('<'):
                    value = value[1:]
                if key == 'service_count' and value == '0':
                    value = 'unlimited'
                emit(rename[key], value, depth)
            elif key in unchanged:
                emit(key, value, depth)
            else:
                raise ValueError('Unreviewed setting: ' + key)
        for child in node['children']:
            name = child['name']
            if name == 'plugin':
                continue
            if name in ['passdb', 'userdb']:
                if child['settings'] != {'args': private['sql_path'], 'driver': 'sql'}:
                    raise ValueError('Only the reviewed SQL passdb/userdb is supported')
                continue
            if name == 'inet_listener':
                name = 'inet_listener quota-status'
            if not name.startswith(('namespace ', 'mailbox ', 'service ', 'protocol ', 'unix_listener ', 'inet_listener ')):
                raise ValueError('Unreviewed configuration section')
            begin(name, depth)
            walk(child, depth + 1)
            if name == 'service auth':
                emit('client_limit', '60000', depth + 1)
            end(depth)
    walk(tree)
    emit('sql_driver', sql['driver'])
    if sql['driver'] != 'sqlite' or sql['default_pass_scheme'] != 'SHA512-CRYPT':
        raise ValueError('Unreviewed SQL driver/password scheme')
    emit('sqlite_path', sql['connect'])
    emit('passdb_default_password_scheme', sql['default_pass_scheme'])
    begin('passdb sql')
    emit('query', sql['password_query'], 1)
    end()
    query = sql['user_query']
    original_quota = "'*:bytes=' || quota AS quota_rule"
    if original_quota not in query or plugin['quota_grace'] != '10%%':
        raise ValueError('Unreviewed quota query/grace policy')
    query = query.replace(original_quota, "quota || 'B' AS quota_storage_size, CAST(quota / 10 AS INTEGER) || 'B' AS quota_storage_grace")
    begin('userdb sql')
    emit('query', query, 1)
    emit('iterate_query', sql['iterate_query'], 1)
    end()
    if plugin['quota'] != 'maildir':
        raise ValueError('Unreviewed quota driver')
    begin('quota user')
    emit('driver', 'maildir', 1)
    end()
    copied = {'quota_status_nouser', 'quota_status_overquota', 'quota_status_success',
        'sieve_max_redirects', 'sieve_pipe_bin_dir', 'sieve_redirect_envelope_from'}
    consumed = {'quota', 'quota_grace', 'sieve', 'sieve_dir'}
    for key, value in plugin.items():
        if key in copied:
            emit(key, value)
        elif key in ['sieve_plugins', 'sieve_global_extensions']:
            boollist(key, value.replace('+', ''))
        elif re.fullmatch(r'sieve_(before|after)\d*', key):
            kind = re.match(r'sieve_(before|after)', key)[1]
            begin('sieve_script ' + key)
            emit('type', kind, 1)
            emit('path', value, 1)
            end()
        elif key in consumed or key.startswith('imapsieve_mailbox'):
            continue
        else:
            raise ValueError('Unreviewed plugin setting: ' + key)
    begin('sieve_script personal')
    emit('path', plugin['sieve_dir'], 1)
    emit('active_path', plugin['sieve'], 1)
    end()
    indexes = sorted({int(re.match(r'imapsieve_mailbox(\d+)_', key)[1])
        for key in plugin if key.startswith('imapsieve_mailbox')})
    for index in indexes:
        prefix = 'imapsieve_mailbox' + str(index) + '_'
        rule = {key[len(prefix):]: value for key, value in plugin.items() if key.startswith(prefix)}
        if set(rule) - {'name', 'from', 'causes', 'before'} or not {'name', 'causes', 'before'} <= set(rule):
            raise ValueError('Unreviewed IMAPSieve rule')
        outer = 'imapsieve_from ' + json.dumps(rule['from']) if 'from' in rule else 'mailbox ' + json.dumps(rule['name'])
        if 'from' in rule and rule['name'] != '*':
            raise ValueError('Combined IMAPSieve source/destination needs separate review')
        begin(outer)
        begin('sieve_script learn' + str(index), 1)
        emit('type', 'before', 2)
        boollist('cause', rule['causes'].lower(), 2)
        emit('path', rule['before'].removeprefix('file:'), 2)
        end(1)
        end()
    begin('service anvil')
    emit('client_limit', '60000', 1)
    end()
    # Preserve trusted localhost authentication for applications using IMAP143;
    # 2.4 no longer bypasses ssl=required merely for login_trusted_networks.
    begin('local 127.0.0.1')
    emit('ssl', 'yes', 1)
    emit('auth_allow_cleartext', 'yes', 1)
    end()
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--parameters', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--storage-version', default='2.3.21', choices=['2.3.21', '2.4.5'])
    args = parser.parse_args()
    parameters = json.loads(args.parameters.read_text())
    result = convert(args.input.read_text(), parameters['sql'], parameters['private'], args.storage_version)
    with args.output.open('x') as stream:
        stream.write(result)
    args.output.chmod(0o600)
