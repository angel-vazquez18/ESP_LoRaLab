#include <assert.h>
#include <stdio.h>
#include <initializer_list>
#include "audio_diagnostics.h"

int main() {
  const uint8_t reference[] = "123456789";
  assert(AudioDiagnostics::crc32(reference, 9) == 0xcbf43926U);
  assert(AudioDiagnostics::crc32(nullptr, 0) == 0);
  const uint8_t binary[] = {0, 255, 128, 13, 10};
  assert(AudioDiagnostics::crc32(binary, 5) == 0xac697d3fU);
  AudioDiagnostics::RawStats stats;
  for (uint32_t value : {0U, 0U, 0xffffffffU, 0xffffffffU, 0xffffffffU, 42U, 0U})
    stats.add(value);
  assert(stats.count == 7 && stats.zeros == 3 && stats.ones == 3 && stats.longestRun == 3);
  puts("PASS: PCM CRC known vectors and raw-word diagnostics");
}
