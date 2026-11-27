#include "source/esp32_source.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <stdatomic.h>

// Pin to the control caller's core: deletion then retires all worker accesses.
typedef struct
{
    encoded_queue *queue;
    TaskHandle_t task;
    atomic_bool stop;
} source_worker;
static void produce(void *argument)
{
    source_worker *w = argument;
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    while (!atomic_load_explicit(&w->stop, memory_order_acquire))
    {
        encoded_queue_step(w->queue, esp_timer_get_time());
        encoded_source_status status;
        encoded_queue_snapshot(w->queue, &status);
        if (status.phase >= SOURCE_FINISHED)
            break;
        // Notification wakes cancellation immediately; actual wake timing is retained.
        ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(10) ? pdMS_TO_TICKS(10) : 1);
    }
    encoded_queue_step(w->queue, esp_timer_get_time());
    vTaskSuspend(NULL);
    for (;;)
        vTaskSuspend(NULL);
}
static void *reserve(void *context, encoded_queue *queue)
{
    (void)context;
    source_worker *w = heap_caps_calloc(1, sizeof(*w), MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (!w)
        return NULL;
    w->queue = queue;
    atomic_init(&w->stop, false);
    if (xTaskCreatePinnedToCore(produce, "encoded_source", 4096, w, uxTaskPriorityGet(NULL) + 1,
                                &w->task, xPortGetCoreID()) != pdPASS)
    {
        heap_caps_free(w);
        return NULL;
    }
    return w;
}
static bool start(void *context, void *worker, int64_t at)
{
    (void)context;
    source_worker *w = worker;
    if (!w || !encoded_queue_start(w->queue, at))
        return false;
    xTaskNotifyGive(w->task);
    return true;
}
static bool stop(void *context, void *worker)
{
    (void)context;
    source_worker *w = worker;
    if (!w)
        return true;

    atomic_store_explicit(&w->stop, true, memory_order_release);
    if (eTaskGetState(w->task) != eSuspended)
        xTaskNotifyGive(w->task);
    int64_t until = esp_timer_get_time() + 250000;
    while (eTaskGetState(w->task) != eSuspended)
    {
        if (esp_timer_get_time() >= until)
            return false;
        vTaskDelay(1);
    }
    vTaskDelete(w->task);
    heap_caps_free(w);
    return true;
}
encoded_worker_port esp32_source_port(void)
{
    return (encoded_worker_port){NULL, reserve, start, stop};
}
