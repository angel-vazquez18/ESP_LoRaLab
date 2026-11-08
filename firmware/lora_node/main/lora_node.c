#include "esp_err.h"

#include "control/node_control.h"
#include "platform/esp32_platform.h"
#include "transport/usb_transport.h"

void app_main(void)
{
    node_platform platform;
    esp32_platform_init(&platform);

    node_control *node = node_control_create(&platform);
    ESP_ERROR_CHECK(node ? ESP_OK : ESP_ERR_NO_MEM);

    usb_transport_run(node);
}
