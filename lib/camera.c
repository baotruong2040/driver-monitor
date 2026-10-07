#include "camera.h"

#include <stdatomic.h>
#include "esp_log.h"
#include "esp_heap_caps.h"

static const char *TAG = "CAMERA";
/* USB capture starts only after sensor configuration and capture checks. */
static atomic_bool s_ready = ATOMIC_VAR_INIT(false);

bool camera_is_ready(void)
{
    return atomic_load_explicit(&s_ready, memory_order_acquire);
}

static esp_err_t camera_init_at_clock(uint32_t xclk_hz)
{
    atomic_store_explicit(&s_ready, false, memory_order_release);
    ESP_LOGI(TAG, "Initializing camera...");

    ESP_LOGI(
        TAG,
        "Free PSRAM: %u bytes",
        (unsigned int)heap_caps_get_free_size(MALLOC_CAP_SPIRAM)
    );

    if (heap_caps_get_total_size(MALLOC_CAP_SPIRAM) == 0)
    {
        ESP_LOGE(TAG, "PSRAM unavailable; enable octal PSRAM for the N16R8 board");
        return ESP_ERR_NO_MEM;
    }

    camera_config_t config = {
        .pin_pwdn = CAM_PIN_PWDN,
        .pin_reset = CAM_PIN_RESET,

        .pin_xclk = CAM_PIN_XCLK,

        .pin_sccb_sda = CAM_PIN_SIOD,
        .pin_sccb_scl = CAM_PIN_SIOC,

        /*
        * D0 = Y2
        * D1 = Y3
        * ...
        * D7 = Y9
        */
        .pin_d0 = CAM_PIN_Y2,  // GPIO11
        .pin_d1 = CAM_PIN_Y3,  // GPIO9
        .pin_d2 = CAM_PIN_Y4,  // GPIO8
        .pin_d3 = CAM_PIN_Y5,  // GPIO10
        .pin_d4 = CAM_PIN_Y6,  // GPIO12
        .pin_d5 = CAM_PIN_Y7,  // GPIO18
        .pin_d6 = CAM_PIN_Y8,  // GPIO17
        .pin_d7 = CAM_PIN_Y9,  // GPIO16

        .pin_vsync = CAM_PIN_VSYNC, // GPIO6
        .pin_href  = CAM_PIN_HREF,  // GPIO7
        .pin_pclk  = CAM_PIN_PCLK,  // GPIO13

        .xclk_freq_hz = xclk_hz,

        .ledc_timer = LEDC_TIMER_0,
        .ledc_channel = LEDC_CHANNEL_0,

        .pixel_format = PIXFORMAT_JPEG,
        .frame_size = FRAMESIZE_HD,

        .jpeg_quality = 10,  // 0-63 lower means better quality
        /* Reserve JPEG headroom for detailed HD frames in PSRAM. */
        .jpeg_buffer_size = CAMERA_JPEG_BUFFER_SIZE,

        .fb_count = 2,
        .fb_location = CAMERA_FB_IN_PSRAM,
        .grab_mode = CAMERA_GRAB_LATEST
    };

    esp_err_t err = esp_camera_init(&config);

    if (err != ESP_OK)
    {
        ESP_LOGE(
            TAG,
            "Camera init failed: 0x%x",
            err
        );

        return err;
    }

    sensor_t *sensor = esp_camera_sensor_get();

    if (sensor == NULL)
    {
        ESP_LOGE(TAG, "Cannot get camera sensor");
        esp_camera_deinit();
        return ESP_FAIL;
    }

    /* Apply format before geometry: OV3660 geometry also selects JPEG PLL
     * and compression settings. Check writes that esp_camera_init ignores. */
    if (sensor->set_pixformat(sensor, PIXFORMAT_JPEG) != 0 ||
        sensor->set_framesize(sensor, config.frame_size) != 0 ||
        sensor->set_quality(sensor, config.jpeg_quality) != 0)
    {
        ESP_LOGE(TAG, "Failed to apply JPEG sensor settings");
        esp_camera_deinit();
        return ESP_FAIL;
    }
    ESP_LOGI(TAG, "Sensor configured: JPEG, %ux%u, quality %d, XCLK %u Hz",
             (unsigned int)resolution[config.frame_size].width,
             (unsigned int)resolution[config.frame_size].height,
             config.jpeg_quality, (unsigned int)config.xclk_freq_hz);
    ESP_LOGI(TAG, "JPEG buffers: %u x %u KB in PSRAM, latest-frame capture",
             (unsigned int)config.fb_count, (unsigned int)(config.jpeg_buffer_size / 1024));

    /*
     * Các giá trị mặc định.
     */
    sensor->set_brightness(sensor, 0);
    sensor->set_contrast(sensor, 0);
    sensor->set_saturation(sensor, 0);

    sensor->set_whitebal(sensor, 1);
    sensor->set_awb_gain(sensor, 1);

    sensor->set_exposure_ctrl(sensor, 1);
    sensor->set_gain_ctrl(sensor, 1);

    /* Verify more frames than the two queued buffers before exposing USB video. */
    for (unsigned int check = 0; check < 4; check++)
    {
        camera_fb_t *test_frame = esp_camera_fb_get();
        if (test_frame == NULL)
        {
            ESP_LOGE(TAG, "No valid JPEG captured at %u MHz; check camera ribbon, power, and D0-D7/PCLK/VSYNC/HREF pin mapping",
                     (unsigned int)(xclk_hz / 1000000));
            esp_camera_deinit();
            return ESP_ERR_TIMEOUT;
        }
        if (test_frame->format != PIXFORMAT_JPEG || test_frame->len < 4 ||
            test_frame->buf[0] != 0xff || test_frame->buf[1] != 0xd8 ||
            test_frame->buf[2] != 0xff ||
            test_frame->buf[test_frame->len - 2] != 0xff ||
            test_frame->buf[test_frame->len - 1] != 0xd9)
        {
            ESP_LOGE(TAG, "Captured frame has invalid JPEG markers");
            esp_camera_fb_return(test_frame);
            esp_camera_deinit();
            return ESP_FAIL;
        }
        if (test_frame->width != resolution[config.frame_size].width ||
            test_frame->height != resolution[config.frame_size].height)
        {
            ESP_LOGE(TAG, "Unexpected frame geometry: %ux%u", (unsigned int)test_frame->width,
                     (unsigned int)test_frame->height);
            esp_camera_fb_return(test_frame);
            esp_camera_deinit();
            return ESP_FAIL;
        }
        ESP_LOGI(TAG, "JPEG capture check %u/4: %ux%u, %u bytes, PSRAM DMA %s", check + 1,
                 (unsigned int)test_frame->width, (unsigned int)test_frame->height,
                 (unsigned int)test_frame->len, esp_camera_get_psram_mode() ? "enabled" : "disabled");
        esp_camera_fb_return(test_frame);
    }

    ESP_LOGI(
        TAG,
        "Camera OK - PID: 0x%04X",
        sensor->id.PID
    );

    ESP_LOGI(
        TAG,
        "PSRAM remaining: %u bytes",
        (unsigned int)heap_caps_get_free_size(MALLOC_CAP_SPIRAM)
    );

    atomic_store_explicit(&s_ready, true, memory_order_release);
    return ESP_OK;
}

esp_err_t camera_init(void)
{
    /* 20 MHz selects the driver's normal faster JPEG PLL profile. OV3660
     * specifies 6-27 MHz input; retain the validated 16 MHz mode as fallback. */
    esp_err_t err = camera_init_at_clock(20000000);
    if (err == ESP_OK)
        return ESP_OK;
    ESP_LOGW(TAG, "20 MHz camera startup failed (%s); retrying at 16 MHz",
             esp_err_to_name(err));
    return camera_init_at_clock(16000000);
}

camera_fb_t *camera_get_frame(void)
{
    return esp_camera_fb_get();
}

void camera_return_frame(camera_fb_t *fb)
{
    if (fb != NULL)
    {
        esp_camera_fb_return(fb);
    }
}


