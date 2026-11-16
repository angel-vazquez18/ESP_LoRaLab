#include <stdatomic.h>
#include <string.h>
#include "sdkconfig.h"
#include "driver/i2s_std.h"
#include "esp_check.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "audio/esp32_audio.h"
#include "audio/pcm_samples.h"
#include "generated/audio_profile.h"

#ifndef CONFIG_LORALAB_AUDIO_PLAYBACK
#define CONFIG_LORALAB_AUDIO_PLAYBACK 0
#endif

#define FRAMES 128U
#define DESCRIPTORS 4U

static struct {
    i2s_chan_handle_t channel;
    bool enabled;
    int16_t *stereo;
    uint32_t target, loaded;
    int64_t last_callback;
    atomic_uint frames, underflows;
    atomic_bool done;
} output;

static bool sent(i2s_chan_handle_t channel, i2s_event_data_t *event, void *context)
{
    (void)channel; (void)context;
    int64_t time = esp_timer_get_time();
    if (output.last_callback && time - output.last_callback > 48000)
        atomic_fetch_add(&output.underflows, 1); // Missed DMA refill deadline.
    output.last_callback = time;
    uint32_t count = event->size / 4;
    uint32_t completed = atomic_fetch_add(&output.frames, count) + count;
    uint32_t available = output.loaded < output.target ? output.target - output.loaded : 0;
    if (available > count) available = count;
    if (available) memcpy(event->dma_buf, output.stereo + output.loaded * 2, available * 4);
    memset((uint8_t *)event->dma_buf + available * 4, 0, event->size - available * 4);
    output.loaded += available;
    if (completed >= output.target) atomic_store(&output.done, true);
    return false;
}
static void stop(void *context)
{
    (void)context;
    // No blocking writer owns this channel; disabling stops callbacks before free.
    if (output.enabled) ESP_ERROR_CHECK(i2s_channel_disable(output.channel));
    output.enabled = false;
    if (output.channel) ESP_ERROR_CHECK(i2s_del_channel(output.channel));
    output.channel = NULL;
    heap_caps_free(output.stereo);
    output.stereo = NULL;
}
static bool start(void *context, uint8_t *pcm, uint32_t samples)
{
    (void)context;
    if (output.channel || !samples || samples > AUDIO_MAX_SAMPLES) return false;
    memset(&output, 0, sizeof(output));
    output.target = samples;
    // Internal RAM keeps bounded ISR refills independent of PSRAM cache access.
    size_t capacity = samples > FRAMES * DESCRIPTORS ? samples : FRAMES * DESCRIPTORS;
    output.stereo = heap_caps_calloc(capacity, 4, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (!output.stereo) return false;
    pcm_output_stereo(pcm, output.stereo, samples);
    i2s_chan_config_t channel = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    channel.dma_desc_num = DESCRIPTORS;
    channel.dma_frame_num = FRAMES;
    i2s_std_config_t config = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(AUDIO_SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {.mclk = I2S_GPIO_UNUSED, .bclk = AUDIO_OUTPUT_BCLK,
                     .ws = AUDIO_OUTPUT_WS, .dout = AUDIO_OUTPUT_DIN, .din = I2S_GPIO_UNUSED},
    };
    if (i2s_new_channel(&channel, &output.channel, NULL) != ESP_OK ||
        i2s_channel_init_std_mode(output.channel, &config) != ESP_OK) goto fail;
    i2s_event_callbacks_t callbacks = {.on_sent = sent};
    if (i2s_channel_register_event_callback(output.channel, &callbacks, NULL) != ESP_OK) goto fail;
    size_t loaded = 0;
    if (i2s_channel_preload_data(output.channel, output.stereo, FRAMES * DESCRIPTORS * 4, &loaded) != ESP_OK ||
        loaded != FRAMES * DESCRIPTORS * 4) goto fail;
    output.loaded = samples < FRAMES * DESCRIPTORS ? samples : FRAMES * DESCRIPTORS;
    if (i2s_channel_enable(output.channel) != ESP_OK) goto fail;
    output.enabled = true;
    return true;
fail:
    stop(NULL);
    return false;
}
static void poll(void *context, node_audio_progress *progress)
{
    (void)context;
    uint32_t frames = atomic_load(&output.frames);
    *progress = (node_audio_progress){.samples = frames < output.target ? frames : output.target,
        .dma_frames = frames, .underflows = atomic_load(&output.underflows),
        .done = atomic_load(&output.done)};
    progress->failed = progress->underflows != 0;
}
node_audio_port esp32_audio_port(void)
{
    return (node_audio_port){.playback = CONFIG_LORALAB_AUDIO_PLAYBACK,
        .start = start, .poll = poll, .stop = stop};
}
