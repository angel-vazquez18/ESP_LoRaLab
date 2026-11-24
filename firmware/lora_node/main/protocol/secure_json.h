#pragma once
#include <stdbool.h>
#include <stddef.h>

typedef void *(*secure_json_allocate_fn)(size_t);
typedef void (*secure_json_release_fn)(void *);
// Install at startup, before any JSON allocation. NULL/NULL selects malloc/free.
bool secure_json_install(secure_json_allocate_fn, secure_json_release_fn);
void secure_json_ensure(void);
