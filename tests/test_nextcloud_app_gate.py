import re
import shutil
import subprocess
from pathlib import Path

import pytest

NEXTCLOUD = (Path(__file__).parents[1] / 'setup/nextcloud.sh').read_text(encoding='utf-8')


def test_install_gate_also_tracks_pinned_app_versions():
    gate = re.search(r'^if \[ ! -d /usr/local/lib/owncloud/ \].*?; then$', NEXTCLOUD, re.M | re.S).group(0)
    assert '"$(installed_app_ver contacts)" != "$contacts_ver"' in gate
    assert '"$(installed_app_ver calendar)" != "$calendar_ver"' in gate


@pytest.mark.skipif(not shutil.which('bash'), reason='bash required')
def test_installed_app_ver_reads_the_app_version_only(tmp_path):
    info = tmp_path / 'contacts/appinfo/info.xml'
    info.parent.mkdir(parents=True)
    info.write_text('<?xml version="1.0"?>\n<info>\n  <id>contacts</id>\n  <version>8.10.0</version>\n</info>\n')
    func = re.search(r'^installed_app_ver\(\) \{.*\}$', NEXTCLOUD, re.M).group(0)
    func = func.replace('/usr/local/lib/owncloud/apps', '.')
    # Script as LF bytes on stdin: Windows argv quoting and text-mode CRLF would both break bash.
    script = func + '\ninstalled_app_ver contacts\necho "[$(installed_app_ver calendar)]"\n'
    out = subprocess.run(['bash', '-s'], input=script.encode(), capture_output=True, check=True,
                         cwd=tmp_path.resolve()).stdout.decode()
    assert out.split() == ['8.10.0', '[]']
