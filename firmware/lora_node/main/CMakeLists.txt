idf_component_register(
    SRCS
        "lora_node.c"
        "radio/esp32_radio.c"
        "radio/node_radio.c"
        "radio/radio_config_json.c"
        "radio/rf_frames.c"
        "radio/rf_fragments.c"
        "radio/rf_reassembly.c"
        "radio/rf_ack.c"
        "radio/rf_sender.c"
        "radio/rf_execution.c"
        "security/frame_crypto.c"
        "security/session_crypto.c"
        "security/crypto_benchmark.c"
        "radio/vendor/sx126x/sx126x.c"
        "audio/esp32_audio.c"
        "audio/pcm_samples.c"
        "audio/codec_clip.c"
        "platform/esp32_platform.c"
        "platform/esp32_ptt.c"
        "platform/esp32_display.c"
        "transport/usb_transport.c"
        "control/node_control.c"
        "memory/observations.c"
        "input/ptt_gate.c"
        "display/node_view.c"
        "display/oled_panel.c"
        "artifacts/artifact_store.c"
        "protocol/strict_json.c"
        "protocol/secure_json.c"
        "protocol/chunk_bytes.c"
    INCLUDE_DIRS "." "radio/vendor/sx126x"
    REQUIRES esp_driver_usb_serial_jtag esp_timer esp_system esp_hw_support
             esp_driver_i2s esp_driver_spi esp_driver_gpio esp_driver_i2c
             nvs_flash espressif__cjson mbedtls heap esp_app_format loralab_codec2
)

# Board reference file.
set(BOARD_PROFILE_FILE
    "${CMAKE_CURRENT_LIST_DIR}/../../../hardware/boards/heltec_wifi_lora32_v4.json"
)

# Reconfigure when the profile changes.
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    "${BOARD_PROFILE_FILE}"
)

# Fingerprint the exact file bytes.
file(SHA256 "${BOARD_PROFILE_FILE}" BOARD_PROFILE_SHA256)

# Expose the hash as a C string.
target_compile_definitions(${COMPONENT_LIB} PRIVATE
    "BOARD_PROFILE_SHA256=\"${BOARD_PROFILE_SHA256}\""
)
