#!/usr/bin/env python3
"""Adapt legacy HTTP/2 listeners to the current nginx server directive."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


def tokens(text):
    result = []
    offset = 0
    while offset < len(text):
        if text[offset].isspace():
            offset += 1
            continue
        if text[offset] == '#':
            end = text.find('\n', offset)
            offset = len(text) if end < 0 else end + 1
            continue
        start = offset
        if text[offset] in '{};':
            result.append((text[offset], offset, offset + 1))
            offset += 1
            continue
        if text[offset] in "\"'":
            quote = text[offset]
            offset += 1
            while offset < len(text):
                if text[offset] == '\\':
                    offset += 2
                elif text[offset] == quote:
                    offset += 1
                    break
                else:
                    offset += 1
            else:
                raise ValueError('Unterminated nginx string')
            result.append((text[start + 1:offset - 1], start, offset))
            continue
        while offset < len(text) and not text[offset].isspace() and text[offset] not in '{};#':
            if text.startswith('${', offset):
                end = text.find('}', offset + 2)
                if end < 0:
                    raise ValueError('Unterminated braced variable')
                offset = end + 1
            elif text[offset] == '\\':
                offset += 2
            else:
                offset += 1
        result.append((text[start:offset], start, offset))
    return result


def adapt(text, version):
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)', version)
    if not match:
        raise ValueError('Unrecognised nginx version')
    if tuple(map(int, match.groups())) < (1, 25, 1):
        return text
    stack = []
    pending = []
    edits = []
    for token in tokens(text):
        value, start, end = token
        punctuation = end - start == 1 and value in '{};' and text[start] == value
        if punctuation and value == '{':
            stack.append({'name': pending[0][0] if pending else '', 'open': token,
                          'header': pending[:], 'directives': []})
            pending = []
        elif punctuation and value == ';':
            if stack:
                stack[-1]['directives'].append(pending)
            pending = []
        elif punctuation and value == '}':
            if pending or not stack:
                raise ValueError('Unexpected nginx block boundary')
            block = stack.pop()
            if block['name'] != 'server':
                continue
            listeners = [entry for entry in block['directives'] if entry and entry[0][0] == 'listen']
            legacy = [entry for entry in listeners if any(part[0] == 'http2' for part in entry[1:])]
            if not legacy:
                continue
            if len(legacy) != len(listeners):
                raise ValueError('Mixed HTTP/2 listener scope requires review')
            directives = [entry for entry in block['directives'] if entry and entry[0][0] == 'http2']
            if any(len(entry) != 2 or entry[1][0] != 'on' for entry in directives):
                raise ValueError('Conflicting HTTP/2 server policy')
            for entry in legacy:
                for part in entry[1:]:
                    if part[0] == 'http2':
                        edits.append((part[1], part[2], ''))
            if not directives:
                line_start = text.rfind('\n', 0, block['header'][0][1]) + 1
                indentation = re.match(r'[ \t]*', text[line_start:]).group()
                edits.append((block['open'][2], block['open'][2], '\n' + indentation + '\thttp2 on;'))
            pending = []
        else:
            pending.append(token)
    if stack or pending:
        raise ValueError('Incomplete nginx configuration')
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def installed_version():
    result = subprocess.run(['nginx', '-v'], capture_output=True, text=True, check=True)
    match = re.search(r'nginx/(\d+\.\d+\.\d+)', result.stderr + result.stdout)
    if not match:
        raise ValueError('Installed nginx version unavailable')
    return match.group(1)


def reconcile(path, version, apply=False):
    if path.is_symlink():
        raise ValueError('Refusing a symlinked generated configuration')
    before = path.read_text()
    after = adapt(before, version)
    if apply and after != before:
        info = path.stat()
        with tempfile.NamedTemporaryFile(prefix='.nginx-http2-', dir=path.parent, delete=False) as stream:
            candidate = Path(stream.name)
            stream.write(after.encode())
        try:
            os.chown(candidate, info.st_uid, info.st_gid)
            candidate.chmod(info.st_mode & 0o777)
            os.replace(candidate, path)
        finally:
            candidate.unlink(missing_ok=True)
    print(json.dumps({'changed': before != after, 'applied': apply, 'version': version}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', type=Path, required=True)
    parser.add_argument('--version')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    reconcile(args.file, args.version or installed_version(), args.apply)
