"""SQLite boundary regressions, independently of any edition.

Run as root on Linux: python3 tests/test_sqlite_chroot_boundary.py
These test SQLite/chroot and an outside read-only lookup worker. They do not
claim to start Postfix. Native Postfix integration is a separate acceptance test.
SPDX-License-Identifier: CC0-1.0
"""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(os.name == 'posix' and hasattr(os, 'geteuid') and os.geteuid() == 0,
                     'Requires POSIX root for the chroot boundary')
class SQLiteBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='miab-sqlite-boundary-')
        self.root = Path(self.temporary.name)
        self.jail = self.root / 'jail'
        self.jail.mkdir()
        self.path = self.root / 'users.sqlite'
        self.writer = sqlite3.connect(self.path)
        self.writer.execute('PRAGMA journal_mode=WAL')
        self.writer.execute('CREATE TABLE users (email TEXT UNIQUE)')
        self.writer.execute('INSERT INTO users VALUES (?)', ('alpha@example.test',))
        self.writer.commit()

    def tearDown(self):
        self.writer.close()
        self.temporary.cleanup()

    def test_direct_read_needs_wal_paths_outside_chroot(self):
        program = '''import os, sqlite3, sys
connection = sqlite3.connect("file:" + sys.argv[1] + "?mode=ro", uri=True)
os.chroot(sys.argv[2])
os.chdir("/")
try:
    connection.execute("SELECT email FROM users").fetchall()
except sqlite3.OperationalError:
    print("blocked by boundary")
else:
    raise SystemExit("WAL unexpectedly readable across the jail")
'''
        result = subprocess.run([sys.executable, '-c', program, str(self.path), str(self.jail)],
                                capture_output=True, text=True, timeout=10, check=True)
        self.assertEqual(result.stdout.strip(), 'blocked by boundary')

    def test_outside_readonly_worker_serves_chroot_client(self):
        reader = sqlite3.connect('file:' + str(self.path) + '?mode=ro', uri=True)
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(self.jail / 'proxy.sock'))
        listener.listen(1)
        listener.settimeout(10)
        program = '''import json, os, socket, sys
os.chroot(sys.argv[1])
os.chdir("/")
with socket.socket(socket.AF_UNIX) as client:
    client.connect("/proxy.sock")
    client.sendall(b"alpha@example.test\\n")
    with client.makefile("rb") as stream:
        print(stream.readline().decode().strip())
'''
        process = subprocess.Popen([sys.executable, '-c', program, str(self.jail)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            channel, _ = listener.accept()
            with channel, channel.makefile('rwb', buffering=0) as stream:
                key = stream.readline().decode().strip()
                rows = reader.execute('SELECT email FROM users WHERE email=?', (key,)).fetchall()
                stream.write(json.dumps(rows).encode() + b'\n')
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(json.loads(stdout), [['alpha@example.test']])
            self.assertEqual(self.writer.execute('SELECT count(*) FROM users').fetchone()[0], 1)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            reader.close()
            listener.close()


if __name__ == '__main__':
    unittest.main()
