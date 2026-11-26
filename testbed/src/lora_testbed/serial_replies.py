"""The bounded reply perturbations used by IF-01 C5."""

import asyncio
import hashlib

from . import v2

VARIANTS = frozenset(("lost_reply", "delayed_reply", "retry_same_identity"))
REPLY_TIMEOUT_S = 0.40
DELAY_S = 0.55


class ReplyProbe:
    def __init__(self, variant, on_record):
        self.variant = variant
        self.on_record = on_record
        self.first = None
        self.timer = None
        self.delivered_delayed = False
        self.write_sha256 = []

    @property
    def retries(self):
        return 0 if self.variant == "lost_reply" else 1

    def record_exchange(self, document):
        if document["direction"] == "host_to_node":
            wire = v2.encode(v2.Command.model_validate(document["record"]))
            self.write_sha256.append(hashlib.sha256(wire).hexdigest())
        self.on_record(document)

    def intercept(self, reply, pending):
        if self.first is not None:
            return self.timer is not None and not self.delivered_delayed
        self.first = reply
        delay = self.variant == "delayed_reply"
        self.on_record(
            {
                "direction": "host_fixture",
                "perturbation": "delay" if delay else "drop",
                "reply": reply.model_dump(),
                "timeout_s": REPLY_TIMEOUT_S,
                "delay_s": DELAY_S if delay else None,
            }
        )
        if delay:
            self.timer = asyncio.get_running_loop().call_later(DELAY_S, self.deliver, pending)
        return True

    def deliver(self, pending):
        if not pending.done():
            self.delivered_delayed = True
            pending.set_result(self.first)

    def close(self):
        if self.timer:
            self.timer.cancel()
