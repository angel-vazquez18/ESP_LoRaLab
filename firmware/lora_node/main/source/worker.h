#pragma once
#include "source/encoded_source.h"

typedef struct
{
    void *context;
    void *(*reserve)(void *, encoded_queue *);
    bool (*start)(void *, void *, int64_t);
    // On success destroys the worker after confirming it cannot access the queue.
    // On failure retains it; callers must retain the queue/reference and retry.
    bool (*stop)(void *, void *);
} encoded_worker_port;
