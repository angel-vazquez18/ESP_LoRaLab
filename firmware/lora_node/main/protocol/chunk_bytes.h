#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

bool chunk_base64_decode(const char *text, uint8_t *output, size_t capacity, size_t *length);
uint32_t chunk_crc32(const void *bytes, size_t length);
