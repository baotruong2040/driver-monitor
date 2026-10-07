#include "camera.h"
#include "drv8833.h"
#include "ldr.h"
#include "usb_camera.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

void app_main(void)
{
    vTaskDelay(pdMS_TO_TICKS(5000)); /* Allow power and host USB state to settle before camera startup. */
    ESP_LOGI("APP", "USB UVC MJPEG: HD, 1 KB payloads, latest-frame capture");
    esp_err_t err = drv8833_init();
    if (err != ESP_OK)
    {
        ESP_LOGE("APP", "Startup stopped: DRV8833 initialization failed (%s)", esp_err_to_name(err));
        return;
    }
    drv8833_set_day();

    err = ldr_start();
    if (err != ESP_OK)
    {
        ESP_LOGE("APP", "LDR startup failed: %s", esp_err_to_name(err));
    }
    err = camera_init();
    if (err != ESP_OK)
    {
        ESP_LOGE("APP", "Startup stopped: camera initialization failed (%s)", esp_err_to_name(err));
        return;
    }
    err = usb_camera_start();
    if (err != ESP_OK)
    {
        ESP_LOGE("APP", "USB camera initialization failed (%s)", esp_err_to_name(err));
    }
}

