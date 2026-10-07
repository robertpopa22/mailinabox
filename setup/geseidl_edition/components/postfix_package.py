#!/usr/bin/env python3
"""Build-only optional Postfix packages retaining native distribution integration.

The caller authenticates the distribution baseline and publisher signature. This
recipe also pins the exact publisher archive. It never installs packages, runs
maintainer scripts, or changes a live queue/configuration.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

VERSION = '3.11.7'
RELEASE = VERSION + '+geseidl2'
SOURCE_SHA256 = 'a2f3242345753448072177fae83c322a403c9263696996406201145dab8e8625'
SIGNER_FINGERPRINT = '622C7C012254C186677469C50C0B590E80CA15A7'
PACKAGES = ('postfix', 'postfix-sqlite', 'postfix-pcre')


def command(args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT).strip()


def field(control, name, value):
    if '\n' in value or '\r' in value:
        raise ValueError('Control field contains a newline')
    pattern = r'^' + re.escape(name) + r':[^\n]*(?:\n[ \t][^\n]*)*'
    replacement = name + ': ' + value
    if re.search(pattern, control, re.M):
        return re.sub(pattern, lambda match: replacement, control, flags=re.M)
    return control.rstrip() + '\n' + replacement + '\n'


def copy_payload(source, destination, root):
    """Do not follow absolute symlinks retained from a native package."""
    if not destination.is_relative_to(root):
        raise ValueError('Payload destination escapes package root')
    for parent in destination.parents:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('Symlink in package destination parent')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        destination.unlink()
    if source.is_symlink():
        if destination.exists():
            destination.unlink()
        destination.symlink_to(os.readlink(source))
    else:
        shutil.copy2(source, destination)


def build(work, source_archive, baselines, maintainer):
    if work.exists() or work.is_symlink():
        raise ValueError('Build directory exists; inspect before retry')
    if not re.fullmatch(r'[^<>\r\n]+ <[^<>\r\n@]+@[^<>\r\n@]+>', maintainer):
        raise ValueError('Expected a maintainer name and email')
    if hashlib.sha256(source_archive.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError('Publisher source hash mismatch')
    native = {}
    for baseline in baselines:
        package = command(['dpkg-deb', '--field', str(baseline), 'Package'])
        if package not in PACKAGES or package in native:
            raise ValueError('Expected one core, SQLite and PCRE native package')
        native[package] = baseline
        if command(['dpkg-deb', '--field', str(baseline), 'Architecture']) != command(['dpkg', '--print-architecture']):
            raise ValueError('Native baseline does not match the build architecture')
    if set(native) != set(PACKAGES):
        raise ValueError('Missing native package integration')
    work.mkdir(mode=0o700, parents=True)
    with tarfile.open(source_archive) as archive:
        archive.extractall(work, filter='data')
    source = work / ('postfix-' + VERSION)
    options = ['make', '-f', 'Makefile.init', 'makefiles', 'dynamicmaps=yes', 'shared=yes',
        'pie=yes', 'config_directory=/etc/postfix', 'meta_directory=/etc/postfix',
        'daemon_directory=/usr/lib/postfix/sbin', 'shlib_directory=/usr/lib/postfix',
        'command_directory=/usr/sbin', 'queue_directory=/var/spool/postfix',
        'data_directory=/var/lib/postfix', 'sendmail_path=/usr/sbin/sendmail',
        'mailq_path=/usr/bin/mailq', 'newaliases_path=/usr/bin/newaliases',
        'manpage_directory=/usr/share/man',
        'CCARGS=-DUSE_TLS -DUSE_SASL_AUTH -DUSE_CYRUS_SASL -DHAS_SQLITE -DHAS_PCRE=2 '
        '-I/usr/include/sasl -I/usr/include/tirpc -D_FORTIFY_SOURCE=3 '
        '-fstack-protector-strong -Wformat -Werror=format-security',
        'AUXLIBS=-lssl -lcrypto -lsasl2', 'AUXLIBS_SQLITE=-lsqlite3 -lpthread',
        'AUXLIBS_PCRE=-lpcre2-8', 'DEBUG=-g', 'OPT=-O2',
        'SHLIB_RPATH=-Wl,--enable-new-dtags -Wl,-z,relro -Wl,-z,now -Wl,-rpath,/usr/lib/postfix']
    payload = work / 'payload'
    payload.mkdir(mode=0o700)
    with (work / 'build.log').open('w') as log:
        for args in [options, ['make', '-j2'], ['make', 'non-interactive-package',
            'install_root=' + str(payload), 'config_directory=/etc/postfix',
            'meta_directory=/etc/postfix', 'daemon_directory=/usr/lib/postfix/sbin',
            'shlib_directory=/usr/lib/postfix', 'command_directory=/usr/sbin',
            'queue_directory=/var/spool/postfix', 'data_directory=/var/lib/postfix',
            'sendmail_path=/usr/sbin/sendmail', 'mailq_path=/usr/bin/mailq',
            'newaliases_path=/usr/bin/newaliases', 'manpage_directory=/usr/share/man']]:
            subprocess.run(args, cwd=source, stdout=log, stderr=subprocess.STDOUT, check=True)
    built = []
    for package in PACKAGES:
        baseline = native[package]
        stage = work / package
        subprocess.run(['dpkg-deb', '--raw-extract', str(baseline), str(stage)], check=True)
        selected = []
        if package == 'postfix':
            for tree in ('usr/sbin', 'usr/lib/postfix/sbin'):
                selected.extend(path for path in (payload / tree).rglob('*') if not path.is_dir())
            selected.extend((payload / 'usr/lib/postfix').glob('libpostfix-*.so*'))
            selected.append(payload / 'etc/postfix/postfix-files')
            # Native mailq/newaliases alternatives and unit/maintainer scripts
            # stay intact. All executable/library ABI comes from one build.
        else:
            selected.append(payload / 'usr/lib/postfix' / (package + '.so'))
        for path in selected:
            if not path.exists() and not path.is_symlink():
                raise RuntimeError('Missing compiled payload: ' + str(path.relative_to(payload)))
            copy_payload(path, stage / path.relative_to(payload), stage)
        if package == 'postfix':
            # Publisher installs these into daemon_directory. Ubuntu also
            # carries legacy configuration-directory entry points.
            for name in ('post-install', 'postfix-script'):
                copy_payload(payload / 'usr/lib/postfix/sbin' / name,
                             stage / 'etc/postfix' / name, stage)
            for filename in ('libmilter.a', 'libxsasl.a'):
                original = source / 'lib' / filename
                if original.exists():
                    copy_payload(original, stage / 'usr/lib/postfix' / filename, stage)
        plugin_manuals = {'postfix-sqlite': 'sqlite_table.5', 'postfix-pcre': 'pcre_table.5'}
        for page in (payload / 'usr/share/man').rglob('*'):
            if not page.is_file() or page.is_symlink():
                continue
            owner = next((name for name, filename in plugin_manuals.items() if page.name == filename), 'postfix')
            if owner != package:
                continue
            compressed = work / ('manual-' + page.name + '.gz')
            compressed.write_bytes(gzip.compress(page.read_bytes(), mtime=0))
            destination = stage / page.relative_to(payload)
            copy_payload(compressed, destination.with_name(destination.name + '.gz'), stage)
            destination.with_name(destination.name + '.gz').chmod(0o644)
        (stage / 'usr/share/doc' / package / 'README.Geseidl').write_text(
            'Publisher Postfix ' + VERSION + ', source SHA256 ' + SOURCE_SHA256 + '.\n'
            'Executables, shared-library ABI and manuals come from one build.\n'
            'Native distribution service, maintainer scripts and configuration handling are retained.\n'
            'Install all three packages together; validate a private queue and recovery first.\n')
        control_path = stage / 'DEBIAN/control'
        control = control_path.read_text()
        previous = command(['dpkg-deb', '--field', str(baseline), 'Version'])
        if package != 'postfix':
            control = control.replace('postfix (= ' + previous + ')', 'postfix (= ' + RELEASE + ')')
        control = field(control, 'Version', RELEASE)
        control = field(control, 'Maintainer', maintainer)
        control = field(control, 'X-Upstream-Source-SHA256', SOURCE_SHA256)
        control = field(control, 'X-Upstream-Signer-Fingerprint', SIGNER_FINGERPRINT)
        control = field(control, 'Installed-Size', str(sum(
            p.stat().st_size for p in stage.rglob('*') if p.is_file() and not p.is_symlink()) // 1024))
        control_path.write_text(control)
        checksums = []
        for path in sorted(stage.rglob('*')):
            if path.is_file() and not path.is_symlink() and 'DEBIAN' not in path.relative_to(stage).parts:
                checksums.append(hashlib.md5(path.read_bytes()).hexdigest() + '  ' + path.relative_to(stage).as_posix())
        (stage / 'DEBIAN/md5sums').write_text('\n'.join(checksums) + '\n')
        architecture = command(['dpkg-deb', '--field', str(baseline), 'Architecture'])
        output = work / (package + '_' + RELEASE + '_' + architecture + '.deb')
        subprocess.run(['dpkg-deb', '--build', str(stage), str(output)], check=True)
        built.append({'package': package, 'version': RELEASE,
            'baseline_sha256': hashlib.sha256(baseline.read_bytes()).hexdigest(),
            'sha256': hashlib.sha256(output.read_bytes()).hexdigest()})
    result = {'packages': built, 'publisher_version': VERSION,
              'source_sha256': SOURCE_SHA256, 'installed': False,
              'native_service_integration_retained': True}
    (work / 'build-manifest.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, action='append', required=True)
    parser.add_argument('--maintainer', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    build(args.work.resolve(), args.source.resolve(), [p.resolve() for p in args.baseline], args.maintainer)
