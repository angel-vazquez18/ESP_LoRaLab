# Keep firmware and testbed in one repository

The user wants firmware and the working host testbed in ESP_LoraLab, with durable
context for agent-assisted development. Keep independent ESP-IDF projects under
firmware/ and the existing Python/React application under testbed/, sharing root
contracts, hardware plans, procedures and context. This makes cross-language wire
changes reviewable together while preserving independent toolchains and the
existing host adapter/lifecycle implementation instead of rewriting it.
