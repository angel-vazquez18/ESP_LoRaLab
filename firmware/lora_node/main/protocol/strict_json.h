#pragma once
#include <stdbool.h>
#include <stddef.h>
#include "cJSON.h"

// Input must have a terminator at line[length]. Caller deletes the result.
cJSON *strict_json_object(const char *line, size_t length);

// Distinguish integer tokens from 1.0 or 1e0, which cJSON also stores as doubles.
bool strict_json_integer(const cJSON *value);
