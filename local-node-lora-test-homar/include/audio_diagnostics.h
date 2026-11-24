#pragma once

#include <stddef.h>
#include <stdint.h>

namespace AudioDiagnostics {

// IEEE CRC-32, matching Python zlib.crc32. Used for PCM export and RF framing.
inline uint32_t crc32(const uint8_t* bytes, size_t length) {
  uint32_t crc = 0xffffffffU;
  for (size_t i = 0; i < length; ++i) {
    crc ^= bytes[i];
    for (unsigned bit = 0; bit < 8; ++bit) {
      crc = (crc >> 1) ^ ((crc & 1U) ? 0xedb88320U : 0U);
    }
  }
  return crc ^ 0xffffffffU;
}

struct RawStats {
  size_t count = 0, zeros = 0, ones = 0, longestRun = 0;
  size_t run = 0;
  uint32_t previous = 0;
  void add(uint32_t value) {
    run = count && value == previous ? run + 1 : 1;
    if (run > longestRun) longestRun = run;
    if (value == 0) ++zeros;
    if (value == 0xffffffffU) ++ones;
    previous = value;
    ++count;
  }
};

}  // namespace AudioDiagnostics
