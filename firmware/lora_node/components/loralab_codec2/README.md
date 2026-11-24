# Codec 2 component

Pinned upstream Codec 2 1.2.0 with mode 3200 enabled and all other modes disabled.
`dependency.json` records exact sources, hashes, options and the local allocation-
cleanup patch. LGPL 2.1 text is in `vendor/COPYING`; KISS FFT's additional BSD
notice remains in `vendor/src/kiss_fft.c`.

`core.cmake` shares the exact subset/options between ESP-IDF and native checks.
`codec2_dependency_query` constructs, queries and destroys a real context. The
main control core retains its once-per-startup result; codec operations remain
unavailable until their implementation.

See [source/build provenance, tests and binary distribution notes](../../../../docs/codec2_dependency.md).
