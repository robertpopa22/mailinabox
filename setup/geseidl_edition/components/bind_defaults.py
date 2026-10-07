#!/usr/bin/env python3
"""Preserve existing standard DNS zones across ISC's conffile removal."""
import argparse
from pathlib import Path
import re


def preserve(directory):
    main = directory / 'named.conf'
    original = main.read_text()
    old_include = 'include "/etc/bind/named.conf.default-zones";'
    new_include = 'include "/etc/bind/geseidl-default-zones.conf";'
    if new_include in original:
        if old_include in original or not (directory / 'geseidl-default-zones.conf').is_file():
            raise ValueError('Ambiguous existing default-zone migration')
        if not all((directory / ('geseidl-db.' + suffix)).is_file() for suffix in ['local', '127', '0', '255']):
            raise ValueError('Previously preserved zone file is missing')
        return False
    if original.count(old_include) != 1:
        raise ValueError('Expected one native default-zone include before migration')
    default = (directory / 'named.conf.default-zones').read_text()
    files = re.findall(r'file\s+"(/etc/bind/[^"\n]+)"\s*;', default)
    if set(files) != {'/etc/bind/db.local', '/etc/bind/db.127', '/etc/bind/db.0', '/etc/bind/db.255'}:
        raise ValueError('Nonstandard default-zone files require separate review')
    copies = {}
    for filename in files:
        source = directory / Path(filename).name
        target = directory / ('geseidl-' + source.name)
        copies[target] = source.read_bytes()
        default = default.replace('"' + filename + '"', '"/etc/bind/' + target.name + '"')
    copies[directory / 'geseidl-default-zones.conf'] = default.encode()
    for target, content in copies.items():
        if target.exists() and target.read_bytes() != content:
            raise ValueError('Existing edition file differs: ' + str(target))
    for target, content in copies.items():
        target.write_bytes(content)
        target.chmod(0o644)
    # Deliberately modify the native conffile so dpkg --force-confold retains it.
    main.write_text(original.replace(old_include, new_include))
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('/etc/bind'))
    args = parser.parse_args()
    print('preserved' if preserve(args.directory) else 'already preserved')
