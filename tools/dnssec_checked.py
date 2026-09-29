#!/usr/bin/python3
"""Keep successful DNSSEC maintenance in syslog; surface all failures to cron."""
import subprocess
import sys
import syslog


def main():
    try:
        result = subprocess.run(['/root/mailinabox/tools/dns_update'], capture_output=True,
                                text=True, timeout=600, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f'DNSSEC update failed: {type(exc).__name__}', file=sys.stderr)
        return 1
    syslog.openlog('geseidl-dnssec')
    if result.returncode:
        print(result.stdout, end='')
        print(result.stderr, end='', file=sys.stderr)
        print(f'DNSSEC update failed: exit={result.returncode}', file=sys.stderr)
        return result.returncode
    if result.stdout.strip():
        syslog.syslog(syslog.LOG_INFO, result.stdout.strip())
    # Successful exit must not hide warnings written to stderr.
    if result.stderr:
        print(result.stderr, end='', file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
