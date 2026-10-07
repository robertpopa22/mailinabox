# Upstream contributions

## BP-MIAB-009 — Prove portability without the edition

Historical README statements about automatic rebases and complete upstream
alignment disagreed with the reviewed selective-integration policy and actual Git
graph. A fix working in an edition deployment does not prove upstream portability.

Prepare the general correction on an exact upstream commit, retain upstream
defaults and licensing, and run independent tests with no edition marker/package.
Keep local policies and release channels in the separate edition. Track prepared,
submitted and accepted states separately; retire duplicates only after testing
the accepted upstream implementation. Directive: MIAB-02, MIAB-09, MIAB-12.
