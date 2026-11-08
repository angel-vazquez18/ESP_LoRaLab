idf_component_register(
    SRCS
        "lora_node.c"
        "platform/esp32_platform.c"
        "transport/usb_transport.c"
        "control/node_control.c"
        "protocol/strict_json.c"
    INCLUDE_DIRS "."
    REQUIRES esp_driver_usb_serial_jtag esp_timer esp_system esp_hw_support
             nvs_flash espressif__cjson mbedtls heap esp_app_format
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
