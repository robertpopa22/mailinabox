import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('nsd_package', Path(__file__).parents[1] / 'setup/geseidl_edition/components/nsd_package.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_control_replacement_preserves_dependency_continuation():
    native = 'Package: nsd\nVersion: 4.8.0\nDepends: libc6,\n libevent\nDescription: DNS daemon\n extended description\n'
    changed = module.replace_field(native, 'Version', '4.15.2+geseidl1')
    assert 'Depends: libc6,\n libevent\n' in changed
    assert 'Description: DNS daemon\n extended description\n' in changed
    assert 'Version: 4.15.2+geseidl1\n' in changed


def test_control_injection_rejected():
    with pytest.raises(ValueError):
        module.replace_field('Version: 1\n', 'Version', '2\nDepends: attacker')


def test_source_hash_checked_before_build_directory_creation(tmp_path):
    source = tmp_path / 'source.tar.gz'
    source.write_bytes(b'untrusted archive')
    work = tmp_path / 'work'
    with pytest.raises(ValueError, match='hash mismatch'):
        module.build(work, source, tmp_path / 'baseline.deb', 'Example Maintainer <maintainer@example.org>')
    assert not work.exists()
