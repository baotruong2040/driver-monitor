#include "drv8833.h"

#include "esp_log.h"
#include "driver/ledc.h"

/* Camera uses LEDC timer/channel 0; reserve timer/channel 1 for IR. */
#define IR_PWM_TIMER LEDC_TIMER_1
#define IR_PWM_CHANNEL LEDC_CHANNEL_1
#define IR_PWM_DUTY 788 /* About 35% duty with 10-bit PWM (358/1024). */
#define IR_PWM_HZ 1000 /* Longer on/off pulses to test the external LED circuit. */

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

static const char *TAG = "DRV8833";

static bool s_night = false;
static bool s_ir_on = false;
static bool s_mode_known = false;
/* Keep GPIO transitions and mode state synchronized between tasks. */
static SemaphoreHandle_t s_control_mutex;

esp_err_t drv8833_init(void)
{
    if (s_control_mutex != NULL)
    {
        return ESP_ERR_INVALID_STATE;
    }
    gpio_config_t config = {
        .pin_bit_mask =
            (1ULL << DRV_IN1) |
            (1ULL << DRV_IN2) |
            (1ULL << DRV_IN3) |
            (1ULL << DRV_IN4),

        .mode = GPIO_MODE_OUTPUT,

        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,

        .intr_type = GPIO_INTR_DISABLE
    };

    esp_err_t err = gpio_config(&config);

    if (err != ESP_OK)
    {
        ESP_LOGE(
            TAG,
            "GPIO config failed: %s",
            esp_err_to_name(err)
        );

        return err;
    }

    const ledc_timer_config_t ir_timer = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .duty_resolution = LEDC_TIMER_10_BIT,
        .timer_num = IR_PWM_TIMER,
        .freq_hz = IR_PWM_HZ,
        .clk_cfg = LEDC_AUTO_CLK
    };
    err = ledc_timer_config(&ir_timer);
    if (err != ESP_OK)
    {
        return err;
    }
    const ledc_channel_config_t ir_channel = {
        .gpio_num = DRV_IN4,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = IR_PWM_CHANNEL,
        .intr_type = LEDC_INTR_DISABLE,
        .timer_sel = IR_PWM_TIMER,
        .duty = 0,
        .hpoint = 0
    };
    err = ledc_channel_config(&ir_channel);
    if (err != ESP_OK)
    {
        return err;
    }

    s_control_mutex = xSemaphoreCreateRecursiveMutex();
    if (s_control_mutex == NULL)
    {
        return ESP_ERR_NO_MEM;
    }

    /*
     * Boot -> tất cả output LOW.
     */
    gpio_set_level(DRV_IN1, 0);
    gpio_set_level(DRV_IN2, 0);

    gpio_set_level(DRV_IN3, 0);
    ESP_ERROR_CHECK(ledc_set_duty(LEDC_LOW_SPEED_MODE, IR_PWM_CHANNEL, 0));
    ESP_ERROR_CHECK(ledc_update_duty(LEDC_LOW_SPEED_MODE, IR_PWM_CHANNEL));

    s_night = false;
    s_ir_on = false;
    s_mode_known = false;

    ESP_LOGI(TAG, "DRV8833 initialized");

    return ESP_OK;
}

/* Caller holds the mutex. IN3 stays LOW; IN4 supplies PWM. */
static void set_ir(bool on)
{
    gpio_set_level(DRV_IN3, 0);
    /* The control mutex serializes this pair; no fade service is needed. */
    ESP_ERROR_CHECK(ledc_set_duty(LEDC_LOW_SPEED_MODE, IR_PWM_CHANNEL,
                                on ? IR_PWM_DUTY : 0));
    ESP_ERROR_CHECK(ledc_update_duty(LEDC_LOW_SPEED_MODE, IR_PWM_CHANNEL));
    s_ir_on = on;
    if (on)
    {
        /* Wait beyond one 1 kHz PWM period before checking readback. */
        vTaskDelay(1);
        uint32_t actual = ledc_get_duty(LEDC_LOW_SPEED_MODE, IR_PWM_CHANNEL);
        ESP_LOGI(TAG, "IR PWM requested=%u, actual=%u/1024, frequency=%u Hz", (unsigned int)IR_PWM_DUTY, (unsigned int)actual, (unsigned int)ledc_get_freq(LEDC_LOW_SPEED_MODE, IR_PWM_TIMER));
        if (actual != IR_PWM_DUTY)
            ESP_LOGW(TAG, "IR PWM mismatch: check LEDC configuration");
    }
}

void drv8833_ir_off(void)
{
    xSemaphoreTakeRecursive(s_control_mutex, portMAX_DELAY);
    set_ir(false);
    xSemaphoreGiveRecursive(s_control_mutex);
}

void drv8833_ir_on(void)
{
    xSemaphoreTakeRecursive(s_control_mutex, portMAX_DELAY);
    set_ir(true);
    xSemaphoreGiveRecursive(s_control_mutex);
}

static void set_mode(bool night)
{
    xSemaphoreTakeRecursive(s_control_mutex, portMAX_DELAY);
    if (!s_mode_known || s_night != night || s_ir_on != night)
    {
        if (!night) set_ir(false);
        gpio_set_level(DRV_IN1, !night);
        gpio_set_level(DRV_IN2, night);
        vTaskDelay(pdMS_TO_TICKS(IR_CUT_PULSE_MS));
        /* Release the IR-CUT coil after the pulse. */
        gpio_set_level(DRV_IN1, 0);
        gpio_set_level(DRV_IN2, 0);
        if (night) set_ir(true);
        s_night = night;
        s_mode_known = true;
        ESP_LOGI(TAG, "%s active", night ? "NIGHT" : "DAY");
    }
    xSemaphoreGiveRecursive(s_control_mutex);
}

void drv8833_set_day(void) { set_mode(false); }
void drv8833_set_night(void) { set_mode(true); }

bool drv8833_is_night(void)
{
    xSemaphoreTakeRecursive(s_control_mutex, portMAX_DELAY);
    bool night = s_night;
    xSemaphoreGiveRecursive(s_control_mutex);
    return night;
}

bool drv8833_is_ir_on(void)
{
    xSemaphoreTakeRecursive(s_control_mutex, portMAX_DELAY);
    bool ir_on = s_ir_on;
    xSemaphoreGiveRecursive(s_control_mutex);
    return ir_on;
}
