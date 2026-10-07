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

The recipe keeps response-rate limiting enabled by default, matching the native
Ubuntu baseline instead of adopting the publisher's disabled default. Record and
compare effective control/authentication/security defaults across package origins;
unchanged configuration bytes alone do not prove unchanged policy.

The resulting `nsd_4.15.2+geseidl3_*.deb` is a local release-channel artifact,
not an official NLnet Labs or Ubuntu package. Its manifest records source, native
baseline and artifact hashes. Artifacts and environment values remain outside
this public source repository. Future releases require refreshed pins and tests;
there is no unattended package-channel migration in this implementation.

Sources: [NSD releases](https://nlnetlabs.nl/projects/nsd/download/),
[upstream contribution ledger](../../../docs/upstream/CONTRIBUTIONS.md).

`bind_channel.py --work DIRECTORY --version 9.20.29` stages the five installed
BIND packages from ISC's stable Ubuntu 24.04 repository. It verifies the full
publisher signing-key fingerprint, the InRelease signature, the package-index
checksum and each package checksum. It refuses a different publisher version or
an incomplete package set. Staging writes only to a new private directory and
does not install packages or restart services.

For an existing Ubuntu installation, run `bind_defaults.py` before installing
the ISC packages. ISC removes Ubuntu's default-zone conffiles and replaces an
unmodified `named.conf`. The adapter copies the existing standard zone files
under edition-owned names and updates the include, so `--force-confold` preserves
the configuration. It refuses nonstandard files or conflicts; it does not change
zone data, resolver options, keys or service state. Test both the new and old
packages with these preserved files. Native package integration includes conffile
removal as well as binary/runtime compatibility.

After testing the exact binaries, native service command, effective resolver
configuration, DNSSEC positive/negative answers and old-package recovery, an
operator may use the separate `--enable-channel` option with the same directory
and reviewed version. This persists a Signed-By key and repository limited to
BIND packages; other packages from that origin have negative preference. It
refuses conflicting existing channel files. It installs no packages and leaves
APT refresh and the bounded migration to the operator. The ordinary upstream
Ubuntu channel remains unchanged unless this Geseidl option is explicitly used.

Source: [ISC-maintained BIND packages](https://kb.isc.org/docs/isc-packages-for-bind-9).
