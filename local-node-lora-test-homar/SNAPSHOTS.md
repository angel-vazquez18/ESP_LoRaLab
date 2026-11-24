# Preserved independent LoRa bench snapshots

At this preservation merge, the package in this folder is the unmodified
20-trial encrypted versus unencrypted package from PR #185, commit `849ee4a59a46e779a7392f40832b3d8e9f3baa2c`.
Its original 167 files retain their exact Git blobs and modes. The snapshot
manifest describes those original files; this note and the nested historical
snapshot are later additions. Subsequent changes have their own Git history.

The entire 94-file ten-trial package from PR #184, commit `6dde043ab596076b6b1b987e97583e6de6d1676a`, is preserved
byte-for-byte at [`snapshots/10-trial-bench/`](snapshots/10-trial-bench/).
Its subtree remains `00c18c2417d73ce35413427fdd1230701b07971d`. Both its package manifest and its
58-file frozen-evidence manifest remain unchanged and valid relative to that
nested directory. Historical paths and provenance statements describe the
original packaging, rather than a new physical run.

Run ten-trial commands from the nested package, following its own README and
PlatformIO configuration. Use this folder's README and configuration for the
20-trial comparison. The old ten-trial launcher, firmware, tests, and provenance
are kept together in the nested package; they are not mixed into the current
package's operational files. Each package requires its own documented setup.

This layout resolves independently added files without discarding either
version, rewriting evidence, or integrating either bench with ESP_LoRaLab.
No device access, flashing, radio transmission, or new hardware qualification is
performed by this preservation change.
