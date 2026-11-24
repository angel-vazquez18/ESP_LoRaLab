"""Describe retained RF/security stages without inferring authentication from silence."""


def assess(record):
    protected = record["plan"]["spec"].get("security", "none") == "aes128_gcm"
    sender, receiver = record["sender"], record["receiver"]

    def rows(role, name):
        return [e["data"] for e in record["events"] if e["role"] == role and e["name"] == name]

    arrivals = [e for e in rows(receiver, "rx.frame") if e["frame_type"] == "data"]
    accepted = rows(receiver, "rx.accepted")
    rejected = rows(receiver, "rx.rejected")
    auth = sum(e["stage"] == "authentication" for e in rejected)
    replay = sum(e["stage"] == "replay" for e in rejected)
    verified = bool(record.get("verification", {}) and record["verification"]["bytes_equal"])
    if not protected:
        classification = "unprotected"
    elif verified:
        classification = "verified_delivery"
    elif auth:
        classification = "authentication_rejected_after_rf_arrival"
    elif record.get("failure_stage") == "configuring" and not arrivals:
        classification = "host_configuration_rejected_before_rf"
    elif not arrivals:
        classification = "no_data_arrival_observed"
    else:
        classification = "partial_or_no_authenticated_acceptance"
    return {
        "profile": "aes128_gcm" if protected else "none",
        "classification": classification,
        "receiver_data_arrivals": len(arrivals),
        "receiver_crc_valid_data_arrivals": sum(e["crc_ok"] for e in arrivals),
        "node_reported_authenticated_fragments": len(accepted) if protected else 0,
        "authentication_rejections": auth,
        "replay_rejections": replay,
        "session_rejections": sum(e["stage"] == "session" for e in rejected),
        "sender_ack_authentication_rejections": sum(
            e["stage"] == "authentication" for e in rows(sender, "rx.rejected")
        ),
        "accepted_ack_results": sum(e["status"] == "received" for e in rows(sender, "ack.result")),
        "verified_readback": verified,
        "accounting_complete": bool(
            record.get("accounting") and record["accounting"].get("evidence_complete")
        ),
        "scope": (
            "retained node-reported stages and independently verified readback; "
            "no security success inferred from missing RF"
        ),
    }
