#!/usr/bin/env python3
"""Build the reviewed Ubuntu SpamAssassin cohort; never install or migrate data.

Verify the publisher detached signature separately before invoking this recipe.
The source SHA256 is pinned here. Native Debian packages must be retained from
authenticated APT metadata; the reviewed base is Ubuntu 24.04 version 4.0.0-8ubuntu5.
Stage signed rules for 4.000002 and test recovery before installing the output.
"""
from datetime import datetime, timezone
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
import time
from types import SimpleNamespace

SHA256 = 'c521be978cef3d49b1e139477ca60a0bd498345fc98274796e44161fae49a17f'
PACKAGES = ['spamassassin', 'spamd', 'spamc', 'sa-compile']
VERSION = '4.0.2+geseidl2'
ROOT = None
args = SimpleNamespace(resume=False)

def run(command, log=None, cwd=None):
    if log:
        with (ROOT / log).open('w') as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, cwd=cwd, check=True)
        return ''
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT, cwd=cwd).strip()
    except subprocess.CalledProcessError as error:
        (ROOT / ('error-' + str(__import__('time').time_ns()) + '.private')).write_text(error.output)
        raise

def save(name, value):
    value['verified_at'] = datetime.now(timezone.utc).isoformat()
    (ROOT / name).write_text(json.dumps(value, indent=2))
    print(json.dumps(value))

def compile_source():
    assert json.loads((ROOT / 'prepare.json').read_text())['ok']
    source = ROOT / 'Mail-SpamAssassin-4.0.2'
    run(['perl', 'Makefile.PL', 'INSTALLDIRS=vendor', 'PREFIX=/usr',
         'SYSCONFDIR=/etc', 'LOCALSTATEDIR=/var/lib/spamassassin',
         'CONFDIR=/etc/spamassassin', 'DATADIR=/usr/share/spamassassin',
         'ENABLE_SSL=yes', 'CONTACT_ADDRESS=postmaster@example.invalid'], 'configure.private', source)
    run(['make', '-j2'], 'compile.private', source)
    target = ROOT / 'publisher-install'
    target.mkdir()
    run(['make', 'install', 'DESTDIR=' + str(target)], 'stage-install.private', source)
    save('compile.json', {'ok': True, 'source_sha256': SHA256,
        'staged_files': sum(item.is_file() for item in target.rglob('*')),
        'host_library_overwritten': False, 'live_services_changed': False})

def build_packages():
    assert json.loads((ROOT / 'compile.json').read_text())['ok']
    publisher = ROOT / 'publisher-install'
    output = ROOT / 'packages'
    if output.exists():
        assert args.resume
        output.rename(ROOT / ('packages-attempt-' + str(time.time_ns())))
    output.mkdir()
    manifests = []
    def copy(source, target):
        for parent in target.parents:
            if parent.is_symlink():
                raise RuntimeError('Symlinked package parent refused')
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            target.unlink()
        shutil.copy2(source, target)
    for name in PACKAGES:
        package = next((ROOT / 'baseline').glob(name + '_*.deb'))
        target = ROOT / ('package-' + name)
        if target.exists():
            assert args.resume
            target.rename(ROOT / (target.name + '-attempt-' + str(time.time_ns())))
        run(['dpkg-deb', '-R', str(package), str(target)])
        if name == 'spamassassin':
            for relative in ['usr/share/perl5/Mail/SpamAssassin', 'usr/share/spamassassin']:
                old = target / relative
                assert old.resolve().is_relative_to(target.resolve()) and not old.is_symlink()
                old.rename(ROOT / ('retired-' + name + '-' + old.name + '-' + str(time.time_ns())))
            for base in ['usr/share/perl5', 'usr/share/spamassassin']:
                for path in (publisher / base).rglob('*'):
                    if path.is_file():
                        copy(path, target / path.relative_to(publisher))
            # Ubuntu postinst imports this native path; publisher uses a
            # different basename for the same public rule-signing key.
            copy(publisher / 'usr/share/spamassassin/sa-update-pubkey.txt',
                 target / 'usr/share/spamassassin/GPG.KEY')
            for path in (publisher / 'usr/bin').iterdir():
                if path.name not in ['spamd', 'spamc', 'sa-compile']:
                    copy(path, target / 'usr/bin' / path.name)
        else:
            copy(publisher / 'usr/bin' / name, target / ('usr/sbin' if name == 'spamd' else 'usr/bin') / name)
        for path in (publisher / 'usr/share/man').rglob('*'):
            if not path.is_file():
                continue
            if name == 'spamassassin' and path.name.startswith(('spamd.', 'spamc.', 'sa-compile.')):
                continue
            if name != 'spamassassin' and not path.name.startswith(name + '.'):
                continue
            relative = path.relative_to(publisher)
            filename = relative.name + '.gz'
            destination = target / relative.parent / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.is_symlink():
                destination.unlink()
            destination.write_bytes(gzip.compress(path.read_bytes(), mtime=0))
            destination.chmod(0o644)
            if name == 'spamd':
                for native in (target / 'usr/share/man').rglob('*spamd*.gz'):
                    if native != destination and native.is_file() and not native.is_symlink():
                        native.write_bytes(gzip.compress(path.read_bytes(), mtime=0))
        control = target / 'DEBIAN/control'
        text = control.read_text()
        text = re.sub(r'^Version:.*$', 'Version: ' + VERSION, text, flags=re.M)
        text = text.replace('spamassassin (= 4.0.0-8ubuntu5)', 'spamassassin (= ' + VERSION + ')')
        text = re.sub(r'^Installed-Size:.*$', 'Installed-Size: ' + str(sum(path.stat().st_size for path in target.rglob('*')
            if path.is_file() and 'DEBIAN' not in path.parts) // 1024 + 1), text, flags=re.M)
        control.write_text(text)
        hashes = []
        for path in sorted(target.rglob('*')):
            if path.is_file() and not path.is_symlink() and 'DEBIAN' not in path.parts:
                hashes.append(hashlib.md5(path.read_bytes()).hexdigest() + '  ' + str(path.relative_to(target)))
        (target / 'DEBIAN/md5sums').write_text('\n'.join(hashes) + '\n')
        for path in target.rglob('*'):
            os.lchown(path, 0, 0)
            if path.is_dir() and not path.is_symlink():
                path.chmod(0o755)
        arch = run(['dpkg-deb', '-f', str(package), 'Architecture'])
        built = output / (name + '_' + VERSION + '_' + arch + '.deb')
        run(['dpkg-deb', '--build', str(target), str(built)], 'build-' + name + '.private')
        manifests.append({'package': name, 'version': VERSION,
            'sha256': hashlib.sha256(built.read_bytes()).hexdigest()})
    ownership = {}
    for name in PACKAGES:
        target = ROOT / ('package-' + name)
        for path in target.rglob('*'):
            if (path.is_file() or path.is_symlink()) and 'DEBIAN' not in path.parts:
                relative = str(path.relative_to(target))
                assert relative not in ownership, 'Overlapping cohort file ownership: ' + relative
                ownership[relative] = name
    plan = run(['apt-get', '-s', '--no-install-recommends', 'install'] + [str(path) for path in output.glob('*.deb')])
    (ROOT / 'install-plan.private').write_text(plan)
    assert not any(line.startswith('Remv ') for line in plan.splitlines())
    assert {line.split()[1] for line in plan.splitlines() if line.startswith('Inst ')} == set(PACKAGES)
    new = ROOT / 'new-root'
    if new.exists():
        assert args.resume
        new.rename(ROOT / ('new-root-attempt-' + str(time.time_ns())))
    new.mkdir()
    for path in output.glob('*.deb'):
        run(['dpkg-deb', '-x', str(path), str(new)])
    save('packages.json', {'ok': True, 'packages': manifests, 'native_maintainer_service_integration_retained': True,
        'live_services_changed': False})

def build(work, archive, native_debs):
    global ROOT
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError('Publisher source checksum mismatch')
    if os.geteuid() != 0:
        raise PermissionError('Native ownership/package build requires root')
    release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if release.get('ID', '').strip('"') != 'ubuntu' or release.get('VERSION_ID', '').strip('"') != '24.04':
        raise ValueError('Only the reviewed Ubuntu 24.04 baseline is supported')
    native = {}
    for package in native_debs:
        name = subprocess.check_output(['dpkg-deb', '-f', str(package), 'Package'], text=True).strip()
        version = subprocess.check_output(['dpkg-deb', '-f', str(package), 'Version'], text=True).strip()
        arch = subprocess.check_output(['dpkg-deb', '-f', str(package), 'Architecture'], text=True).strip()
        host = subprocess.check_output(['dpkg', '--print-architecture'], text=True).strip()
        if name not in PACKAGES or name in native or version != '4.0.0-8ubuntu5' or arch not in ['all', host]:
            raise ValueError('Unreviewed or duplicate native cohort package')
        native[name] = package
    if set(native) != set(PACKAGES):
        raise ValueError('All four native cohort packages are required')
    ROOT = work.resolve()
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=False)
    with tarfile.open(archive) as contents:
        contents.extractall(ROOT, filter='data')
    baseline = ROOT / 'baseline'
    baseline.mkdir(mode=0o700)
    for name, package in native.items():
        shutil.copy2(package, baseline / (name + '_native.deb'))
    (ROOT / 'prepare.json').write_text(json.dumps({'ok': True, 'source_sha256_verified': True}))
    compile_source()
    build_packages()
    return json.loads((ROOT / 'packages.json').read_text())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--native-deb', type=Path, action='append', required=True)
    options = parser.parse_args()
    os.umask(0o077)
    build(options.work, options.source, options.native_deb)
