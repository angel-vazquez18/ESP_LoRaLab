# Use fresh directional keys for every bench run

On October 18, 2026, the user delegated provisional contract decisions pending
discussion with Homar. Because both nodes are controlled over trusted USB, each
run receives fresh source-specific AES-128-GCM keys in RAM; resets end the session
instead of restoring keys and nonce counters from flash. This avoids persistent
nonce-recovery complexity while making unattended operation and post-restart
session continuation separate future requirements; the exact policy is in
`../testbed_contract_v2.md` (D08–D09).
