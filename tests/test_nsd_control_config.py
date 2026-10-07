"""Validate the generated NSD control settings using the actual NSD parser."""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest


class NsdControlConfigurationTests(unittest.TestCase):
    def test_generated_template_enables_only_local_control(self):
        checker = os.environ.get('NSD_CHECKCONF_BIN') or shutil.which('nsd-checkconf')
        if not checker:
            self.skipTest('NSD configuration parser is not installed')
        source = (Path(__file__).parents[1] / 'setup/dns.sh').read_text()
        initial = re.search(r'cat > /etc/nsd/nsd.conf << EOF;\n(.*?)\nEOF', source, re.S)
        appended = re.findall(r'cat >> /etc/nsd/nsd.conf << EOF;\n(.*?)\nEOF', source, re.S)
        self.assertIsNotNone(initial)
        config = initial.group(1) + '\n' + '\n'.join(appended) + '\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'nsd.conf'
            path.write_text(config)
            def option(name):
                result = subprocess.check_output([checker, '-o', name, str(path)], text=True)
                return shlex.split(result)
            self.assertEqual(option('control-enable'), ['yes'])
            self.assertEqual(option('control-interface'), ['127.0.0.1'])


if __name__ == '__main__':
    unittest.main()
