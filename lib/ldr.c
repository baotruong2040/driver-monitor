#include "ldr.h"

#include "drv8833.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#define LDR_GPIO 2

#define LDR_NIGHT_RAW 200
#define LDR_DAY_RAW 2300
#define LDR_POLL_MS 100
#define LDR_NIGHT_CONFIRM_US (5LL * 1000000)
#define LDR_DAY_CONFIRM_US (15LL * 1000000)
#define LDR_WARNING_INTERVAL_US (10LL * 1000000)
#define LDR_LOG_INTERVAL_US 1000000

_Static_assert(LDR_NIGHT_RAW < LDR_DAY_RAW, "LDR thresholds must have hysteresis");

static const char *TAG = "LDR";
static adc_oneshot_unit_handle_t s_adc;
static adc_channel_t s_channel;
static void ldr_task(void *arg)
{
    (void)arg;
    int64_t change_since = -1, next_warning = 0;
    int64_t next_log = 0;
    bool candidate_night = false;
    TickType_t last_wake = xTaskGetTickCount();

    while (true)
    {
        int raw;
        int64_t now = esp_timer_get_time();
        esp_err_t err = adc_oneshot_read(s_adc, s_channel, &raw);
        bool night = drv8833_is_night();
        bool pending = err == ESP_OK &&
                       (night ? raw >= LDR_DAY_RAW : raw <= LDR_NIGHT_RAW);

        if (!pending)
            change_since = -1;
        else
        {
            if (change_since < 0 || candidate_night == night)
            {
                change_since = now;
                candidate_night = !night;
            }
            int64_t wait_us = night ? LDR_DAY_CONFIRM_US : LDR_NIGHT_CONFIRM_US;
            if (now - change_since >= wait_us)
            {
                if (night) drv8833_set_day();
                else drv8833_set_night();
                night = !night;
                change_since = -1;
                /* Avoid catch-up reads after the 200 ms IR-CUT pulse. */
                last_wake = xTaskGetTickCount();
            }
        }
        if (err == ESP_OK && now >= next_log)
        {
            ESP_LOGI(TAG, "GPIO%d raw=%d (0-4095), mode=%s", LDR_GPIO, raw,
                     night ? "NIGHT" : "DAY");
            next_log = now + LDR_LOG_INTERVAL_US;
        }
        if (err != ESP_OK && now >= next_warning)
        {
            ESP_LOGW(TAG, "ADC read failed: %s", esp_err_to_name(err));
            next_warning = now + LDR_WARNING_INTERVAL_US;
        }
        xTaskDelayUntil(&last_wake, pdMS_TO_TICKS(LDR_POLL_MS));
    }
}

esp_err_t ldr_start(void)
{
    if (s_adc != NULL)
    {
        return ESP_ERR_INVALID_STATE;
    }

    adc_unit_t unit;
    esp_err_t err = adc_oneshot_io_to_channel(LDR_GPIO, &unit, &s_channel);
    if (err != ESP_OK)
    {
        return err;
    }
    /* ADC1 avoids sharing ADC2 with the Wi-Fi driver. */
    if (unit != ADC_UNIT_1)
    {
        return ESP_ERR_INVALID_ARG;
    }
    const adc_oneshot_unit_init_cfg_t unit_config = {
        .unit_id = unit,
        .ulp_mode = ADC_ULP_MODE_DISABLE,
    };
    err = adc_oneshot_new_unit(&unit_config, &s_adc);
    if (err != ESP_OK)
    {
        return err;
    }
    const adc_oneshot_chan_cfg_t channel_config = {
        .atten = ADC_ATTEN_DB_12,
        .bitwidth = ADC_BITWIDTH_12,
    };
    err = adc_oneshot_config_channel(s_adc, s_channel, &channel_config);
    if (err == ESP_OK &&
        xTaskCreate(ldr_task, "ldr", 3072, NULL, 4, NULL) != pdPASS)
    {
        err = ESP_ERR_NO_MEM;
    }
    if (err != ESP_OK)
    {
        adc_oneshot_del_unit(s_adc);
        s_adc = NULL;
    }
    return err;
}
