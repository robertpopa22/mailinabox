import importlib.util
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / 'setup/geseidl_edition/components/bind_defaults.py'
spec = importlib.util.spec_from_file_location('bind_defaults', MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture(tmp_path):
    main = 'include "/etc/bind/named.conf.options";\ninclude "/etc/bind/named.conf.local";\ninclude "/etc/bind/named.conf.default-zones";\n'
    (tmp_path / 'named.conf').write_text(main)
    default = 'zone "." { type hint; file "/usr/share/dns/root.hints"; };\n'
    for zone, name in [('localhost', 'db.local'), ('127.in-addr.arpa', 'db.127'), ('0.in-addr.arpa', 'db.0'), ('255.in-addr.arpa', 'db.255')]:
        default += f'zone "{zone}" {{ type master; file "/etc/bind/{name}"; }};\n'
        (tmp_path / name).write_bytes(('original ' + name).encode())
    (tmp_path / 'named.conf.default-zones').write_text(default)
    return main


def test_native_conffile_removal_preserves_zone_contents(tmp_path):
    main = fixture(tmp_path)
    module.preserve(tmp_path)
    for name in ['named.conf.default-zones', 'db.local', 'db.127', 'db.0', 'db.255']:
        (tmp_path / name).unlink()  # ISC package removes these obsolete conffiles.
    assert not module.preserve(tmp_path)
    assert (tmp_path / 'named.conf').read_text() == main.replace('named.conf.default-zones', 'geseidl-default-zones.conf')
    assert 'file "/usr/share/dns/root.hints"' in (tmp_path / 'geseidl-default-zones.conf').read_text()
    for name in ['db.local', 'db.127', 'db.0', 'db.255']:
        assert (tmp_path / ('geseidl-' + name)).read_bytes() == ('original ' + name).encode()


def test_conflicting_edition_file_refuses_before_native_config_change(tmp_path):
    main = fixture(tmp_path)
    (tmp_path / 'geseidl-db.127').write_text('operator change')
    with pytest.raises(ValueError):
        module.preserve(tmp_path)
    assert (tmp_path / 'named.conf').read_text() == main
    assert not (tmp_path / 'geseidl-db.local').exists()
