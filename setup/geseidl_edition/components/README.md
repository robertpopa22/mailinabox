# Optional publisher release channels

This directory belongs to the Geseidl package. It does not change upstream's
default distribution package selection or require upstream to follow our release
cadence. General compatibility fixes are prepared separately for upstream.

`nsd_package.py` builds NSD4.15.2 from the publisher archive pinned by SHA256,
using an authenticated native NSD package supplied by the operator as the
integration baseline. It retains native service hardening, maintainer scripts and
conffile handling. It replaces binaries/manuals in an isolated package tree;
building does not install a package or restart any running service. Requires
Python3.12+, the native build dependencies, and `dpkg-deb`.

Before installation, test the exact package binaries with an isolated signed DNS
zone, TCP/UDP queries, negative answers, refused recursion, persisted state and
the live configuration read-only. Retain the authenticated old package and prove
recovery. Version-sensitive state formats and service sandbox restrictions must
be checked; a private build prefix passing a query is insufficient.

The resulting `nsd_4.15.2+geseidl1_*.deb` is a local release-channel artifact,
not an official NLnet Labs or Ubuntu package. Its manifest records source, native
baseline and artifact hashes. Artifacts and environment values remain outside
this public source repository. Future releases require refreshed pins and tests;
there is no unattended package-channel migration in this implementation.

Sources: [NSD releases](https://nlnetlabs.nl/projects/nsd/download/),
[upstream contribution ledger](../../../docs/upstream/CONTRIBUTIONS.md).
