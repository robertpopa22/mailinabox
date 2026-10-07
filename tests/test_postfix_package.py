import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('postfix_package',
    Path(__file__).resolve().parents[1] / 'setup/geseidl_edition/components/postfix_package.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_native_absolute_symlink_cannot_overwrite_host_file(tmp_path):
    source = tmp_path / 'new-script'
    source.write_text('new')
    host = tmp_path / 'host-script'
    host.write_text('live')
    stage = tmp_path / 'stage'
    stage.mkdir()
    destination = stage / 'script'
    try:
        destination.symlink_to(host)
    except OSError:
        pytest.skip('OS cannot create symlinks')
    module.copy_payload(source, destination, stage)
    assert host.read_text() == 'live'
    assert destination.read_text() == 'new'
    assert not destination.is_symlink()


def test_symlink_parent_and_escape_refused(tmp_path):
    source = tmp_path / 'source'
    source.write_text('candidate')
    stage = tmp_path / 'stage'
    stage.mkdir()
    with pytest.raises(ValueError, match='escapes'):
        module.copy_payload(source, tmp_path / 'outside', stage)
    try:
        (stage / 'linked').symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip('OS cannot create symlinks')
    with pytest.raises(ValueError, match='parent'):
        module.copy_payload(source, stage / 'linked/outside', stage)
