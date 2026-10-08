import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('spamassassin_package', Path(__file__).parents[1] /
    'setup/geseidl_edition/components/spamassassin_package.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_unknown_source_refused_before_workspace_creation(tmp_path):
    archive = tmp_path / 'unreviewed.tar.gz'
    archive.write_bytes(b'not the approved publisher source')
    workspace = tmp_path / 'build'
    with pytest.raises(ValueError, match='checksum'):
        module.build(workspace, archive, [])
    assert not workspace.exists()
