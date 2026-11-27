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

#ifndef CONFIG_LORALAB_AUDIO_CAPTURE
#define CONFIG_LORALAB_AUDIO_CAPTURE 0
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
static void stop_output(void *context)
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
static bool start_output(void *context, uint8_t *pcm, uint32_t samples)
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
    stop_output(NULL);
    return false;
}
static void poll_output(void *context, node_audio_progress *progress)
{
    (void)context;
    uint32_t frames = atomic_load(&output.frames);
    *progress = (node_audio_progress){.samples = frames < output.target ? frames : output.target,
        .dma_frames = frames, .underflows = atomic_load(&output.underflows),
        .done = atomic_load(&output.done)};
    progress->failed = progress->underflows != 0;
}
static struct {
    i2s_chan_handle_t channel;
    bool enabled;
    uint8_t *pcm;
    uint32_t target, discarded;
    int64_t last_callback;
    atomic_uint samples, frames, overflows, raw_left_nonzero, raw_right_nonzero, raw_left_or, raw_right_or;
    atomic_bool done;
} input;
static bool selected_capture;
static bool received(i2s_chan_handle_t channel, i2s_event_data_t *event, void *context)
{
    (void)channel; (void)context;
    int64_t time = esp_timer_get_time();
    if (input.last_callback && time - input.last_callback > 48000)
        atomic_fetch_add(&input.overflows, 1);
    input.last_callback = time;
    uint32_t frames = event->size / 8;
    atomic_fetch_add(&input.frames, frames);
    uint32_t samples = atomic_load(&input.samples);
    const uint8_t *slots = event->dma_buf;
    for (uint32_t i = 0; i < frames; i++) {
        if (input.discarded < AUDIO_WARMUP_SAMPLES) { input.discarded++; continue; }
        if (samples == input.target) break;
        uint32_t word;
        memcpy(&word, slots + i * 8, sizeof(word)); // Left of two 32-bit Philips slots.
        uint32_t right;
        memcpy(&right, slots + i * 8 + 4, sizeof(right));
        atomic_fetch_add(&input.raw_left_nonzero, word != 0);
        atomic_fetch_add(&input.raw_right_nonzero, right != 0);
        atomic_fetch_or(&input.raw_left_or, word);
        atomic_fetch_or(&input.raw_right_or, right);
        uint16_t value = (uint16_t)pcm_input_sample(word);
        input.pcm[samples * 2] = value & 255;
        input.pcm[samples * 2 + 1] = value >> 8;
        samples++;
    }
    atomic_store(&input.samples, samples);
    if (samples == input.target) atomic_store(&input.done, true);
    return false;
}
static void stop_input(void)
{
    if (input.enabled) ESP_ERROR_CHECK(i2s_channel_disable(input.channel));
    input.enabled = false;
    if (input.channel) ESP_ERROR_CHECK(i2s_del_channel(input.channel));
    input.channel = NULL;
    input.pcm = NULL;
}
static bool start_input(uint8_t *pcm, uint32_t samples)
{
    if (input.channel || !samples || samples > AUDIO_MAX_SAMPLES) return false;
    memset(&input, 0, sizeof(input));
    input.target = samples;
    input.pcm = pcm;
    i2s_chan_config_t channel = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER);
    channel.dma_desc_num = DESCRIPTORS;
    channel.dma_frame_num = FRAMES;
    i2s_std_config_t config = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(AUDIO_SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {.mclk = I2S_GPIO_UNUSED, .bclk = AUDIO_INPUT_BCLK,
                     .ws = AUDIO_INPUT_WS, .dout = I2S_GPIO_UNUSED, .din = AUDIO_INPUT_SD},
    };
    if (i2s_new_channel(&channel, NULL, &input.channel) != ESP_OK ||
        i2s_channel_init_std_mode(input.channel, &config) != ESP_OK) goto fail;
    i2s_event_callbacks_t callbacks = {.on_recv = received};
    if (i2s_channel_register_event_callback(input.channel, &callbacks, NULL) != ESP_OK ||
        i2s_channel_enable(input.channel) != ESP_OK) goto fail;
    input.enabled = true;
    return true;
fail:
    stop_input();
    return false;
}
static bool start(void *context, uint8_t *pcm, uint32_t samples, bool capture)
{
    selected_capture = capture;
    return capture ? start_input(pcm, samples) : start_output(context, pcm, samples);
}
static void stop(void *context)
{
    if (selected_capture) stop_input(); else stop_output(context);
}
static void poll(void *context, node_audio_progress *progress)
{
    if (!selected_capture) { poll_output(context, progress); return; }
    *progress = (node_audio_progress){.samples = atomic_load(&input.samples),
        .dma_frames = atomic_load(&input.frames), .underflows = atomic_load(&input.overflows),
        .done = atomic_load(&input.done),
        .raw_left_nonzero = atomic_load(&input.raw_left_nonzero),
        .raw_right_nonzero = atomic_load(&input.raw_right_nonzero),
        .raw_left_or = atomic_load(&input.raw_left_or),
        .raw_right_or = atomic_load(&input.raw_right_or)};
    progress->failed = progress->underflows != 0;
}
static void memory_buffers(void *context, node_memory_inventory *out)
{
    (void)context;
    size_t capacity = output.target > FRAMES * DESCRIPTORS ? output.target : FRAMES * DESCRIPTORS;
    node_memory_add(out, "audio_playback_stereo", output.stereo, capacity * 4);
    // I2S provider's private DMA rings/handles remain outside the known requested set.
}
node_audio_port esp32_audio_port(void)
{
    return (node_audio_port){.playback = CONFIG_LORALAB_AUDIO_PLAYBACK,
        .capture = CONFIG_LORALAB_AUDIO_CAPTURE, .start = start, .poll = poll, .stop = stop,
        .memory_buffers = memory_buffers};
}
