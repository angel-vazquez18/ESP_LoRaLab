# Physical-only host and procedure-specific node requirements

Status: accepted by user, November 1, 2026.

The user rejected the simulated implementation and requested one-node tests where
no peer is needed, requiring two nodes only for cases that need them. This
supersedes simulation-first delivery guidance without reducing the 23-procedure scope.

Remove virtual device/run/campaign engines and their operator controls. Keep
physical A/B serial connections independent. IF-01, SEC-04 and VOICE-01 operate
on one node at a time; MEM-01/OPS-01 distinguish local and RF cases. Link tests
require two distinct device identities. Physical capability and runner support
remain prerequisites regardless of node count. Future campaigns derive these
requirements from their cases, including one-node local-only campaigns.

Preserve schema compatibility, public vectors, numerical preparation, audio
reference tools and old evidence with its original provenance. In-memory serial
peers exist only in regression tests; software tests and partial diagnostic checks
never qualify physical RF/audio or complete procedures. Full physical execution
and campaign work stays explicitly unavailable until implemented.
