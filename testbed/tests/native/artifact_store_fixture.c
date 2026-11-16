// Include the production store; only this native fixture can seed later states.
#include "artifacts/artifact_store.c"

bool native_artifact_seed_state(artifact_store *store, const char *id, bool committed)
{
    artifact_slot *slot = find(store, id);
    if (!slot)
        return false;
    memset(slot->bytes, 'a', slot->manifest.length_bytes);
    slot->manifest.state = committed ? ARTIFACT_COMMITTED : ARTIFACT_FAILED;
    slot->manifest.next_offset = committed ? slot->manifest.length_bytes : 0;
    return true;
}
