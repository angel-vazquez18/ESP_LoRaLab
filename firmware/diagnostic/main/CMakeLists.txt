idf_component_register(SRCS "main.c" INCLUDE_DIRS "."
    REQUIRES esp_driver_usb_serial_jtag esp_timer esp_system esp_hw_support
             nvs_flash espressif__cjson mbedtls heap esp_app_format)
