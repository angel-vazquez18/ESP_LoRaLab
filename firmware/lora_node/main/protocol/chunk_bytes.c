#include <string.h>

#include "chunk_bytes.h"

static int digit(char c)
{
    if (c >= 'A' && c <= 'Z') return c - 'A';
    if (c >= 'a' && c <= 'z') return c - 'a' + 26;
    if (c >= '0' && c <= '9') return c - '0' + 52;
    return c == '+' ? 62 : c == '/' ? 63 : -1;
}
bool chunk_base64_decode(const char *text, uint8_t *out, size_t capacity, size_t *length)
{
    if (!text || !out || !length) return false;
    *length = 0;
    size_t count = strlen(text);
    if (!count || count % 4 || count > ((capacity + 2) / 3) * 4) return false;
    for (size_t i = 0; i < count; i += 4) {
        int a = digit(text[i]), b = digit(text[i + 1]);
        int c = digit(text[i + 2]), d = digit(text[i + 3]);
        bool last = i + 4 == count;
        size_t bytes = 3;
        if (a < 0 || b < 0) return false;
        if (text[i + 2] == '=') {
            if (!last || text[i + 3] != '=' || (b & 15)) return false;
            c = d = 0;
            bytes = 1;
        } else if (text[i + 3] == '=') {
            if (!last || c < 0 || (c & 3)) return false;
            d = 0;
            bytes = 2;
        } else if (c < 0 || d < 0) return false;
        if (bytes > capacity - *length) return false;
        out[(*length)++] = (uint8_t)((a << 2) | (b >> 4));
        if (bytes > 1) out[(*length)++] = (uint8_t)((b << 4) | (c >> 2));
        if (bytes > 2) out[(*length)++] = (uint8_t)((c << 6) | d);
    }
    return true;
}
uint32_t chunk_crc32(const void *bytes, size_t length)
{
    const uint8_t *data = bytes;
    uint32_t crc = UINT32_MAX;
    for (size_t i = 0; i < length; i++) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; bit++)
            crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1U)));
    }
    return crc ^ UINT32_MAX;
}
