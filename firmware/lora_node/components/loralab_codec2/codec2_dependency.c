#include "codec2_dependency.h"
#include "codec2.h"

_Static_assert(sizeof(short) == 2 && sizeof(float) == 4, "Codec sample/arithmetic format");

bool codec2_dependency_query(unsigned mode, codec2_frame_format *format)
{
    if (!format)
        return false;
    *format = (codec2_frame_format){0};
    if (mode != 3200)
        return false;
    struct CODEC2 *state = codec2_create(CODEC2_MODE_3200);
    if (!state)
        return false;
    int samples = codec2_samples_per_frame(state);
    int bits = codec2_bits_per_frame(state);
    int bytes = codec2_bytes_per_frame(state);
    codec2_destroy(state);
    if (samples != 160 || bits != 64 || bytes != 8)
        return false;
    *format = (codec2_frame_format){samples, bits, bytes, 8000};
    return true;
}

const char *codec2_dependency_version(void) { return CODEC2_VERSION; }
const char *codec2_dependency_revision(void)
{
    return "06d4c11e699b0351765f10398abb4f663a984f36";
}
