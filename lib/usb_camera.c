#include "usb_camera.h"

#include <stdatomic.h>

#include "camera.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "usb_device_uvc.h"
#include "sdkconfig.h"
#include "usb_video_limits.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "tusb.h"

#define USB_CAMERA_BUFFER_SIZE CAMERA_JPEG_BUFFER_SIZE

static const char *TAG = "USB_CAMERA";
static camera_fb_t *s_camera_frame;
static uvc_fb_t s_usb_frame;
static int64_t s_sample_start;
static unsigned int s_frames;
static size_t s_bytes;
static atomic_bool s_restart_sample = ATOMIC_VAR_INIT(true);

static esp_err_t start_capture(uvc_format_t format, int width, int height, int rate, void *context)
{
    (void)context;
    if (!camera_is_ready())
        return ESP_ERR_INVALID_STATE;
    if (format != UVC_FORMAT_JPEG || width != CONFIG_UVC_CAM1_FRAMESIZE_WIDTH || height != CONFIG_UVC_CAM1_FRAMESIZE_HEIGT || rate < 1 || rate > CONFIG_UVC_CAM1_FRAMERATE)
        return ESP_ERR_INVALID_ARG;
    atomic_store_explicit(&s_restart_sample, true, memory_order_release);
    ESP_LOGI(TAG, "Host opened MJPEG %dx%d at %d FPS", width, height, rate);
    return ESP_OK;
}

static void stop_capture(void *context)
{
    (void)context;
    ESP_LOGI(TAG, "Host stopped video capture");
}

static uvc_fb_t *get_frame(void *context)
{
    (void)context;
    if (!camera_is_ready() || s_camera_frame != NULL)
        return NULL;
    camera_fb_t *frame = camera_get_frame();
    if (frame == NULL)
        return NULL;
    if (frame->format != PIXFORMAT_JPEG || frame->len < 4 ||
        frame->len > USB_CAMERA_BUFFER_SIZE || frame->buf[0] != 0xff ||
        frame->buf[1] != 0xd8 || frame->buf[frame->len - 2] != 0xff ||
        frame->buf[frame->len - 1] != 0xd9)
    {
        camera_return_frame(frame);
        return NULL;
    }
    size_t transfer_length = usb_video_frame_length(frame->len);
    if (transfer_length > CAMERA_JPEG_BUFFER_SIZE)
    {
        camera_return_frame(frame);
        return NULL;
    }
    if (transfer_length > frame->len)
    {
        /* The checked-out camera buffer has CAMERA_JPEG_BUFFER_SIZE capacity.
         * Append outside the original JPEG while we own it; retain fb->len. */
        frame->buf[frame->len] = 0;
    }
    s_camera_frame = frame;
    s_usb_frame = (uvc_fb_t) {
        .buf = frame->buf,
        .len = transfer_length,
        .width = frame->width,
        .height = frame->height,
        .format = UVC_FORMAT_JPEG,
        .timestamp = frame->timestamp,
    };
    return &s_usb_frame;
}

static void return_frame(uvc_fb_t *frame, void *context)
{
    (void)context;
    if (frame != &s_usb_frame || s_camera_frame == NULL)
        return;
    int64_t now = esp_timer_get_time();
    if (atomic_exchange_explicit(&s_restart_sample, false, memory_order_acq_rel))
    {
        s_sample_start = now;
        s_frames = 0;
        s_bytes = 0;
    }
    s_bytes += s_camera_frame->len;
    s_frames++;
    camera_return_frame(s_camera_frame);
    s_camera_frame = NULL;
    if (now - s_sample_start >= 5000000)
    {
        ESP_LOGI(TAG, "UVC capture %.1f FPS; JPEG %.1f KB; %.1f KB/s", s_frames * 1000000.0 / (now - s_sample_start), s_bytes / (s_frames * 1024.0), s_bytes * 1000000.0 / ((now - s_sample_start) * 1024.0));
        s_frames = 0;
        s_bytes = 0;
        s_sample_start = now;
    }
}

esp_err_t usb_camera_start(void)
{
    if (!camera_is_ready())
        return ESP_ERR_INVALID_STATE;
    uint8_t *buffer = heap_caps_malloc(USB_CAMERA_BUFFER_SIZE, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (buffer == NULL)
        return ESP_ERR_NO_MEM;
    uvc_device_config_t config = {
        .uvc_buffer = buffer,
        .uvc_buffer_size = USB_CAMERA_BUFFER_SIZE,
        .start_cb = start_capture,
        .stop_cb = stop_capture,
        .fb_get_cb = get_frame,
        .fb_return_cb = return_frame,
        .cb_ctx = NULL,
    };
    esp_err_t err = uvc_device_config(0, &config);
    if (err != ESP_OK)
    {
        heap_caps_free(buffer);
        return err;
    }
    err = uvc_device_init();
    if (err != ESP_OK)
    {
        /* The component retains its configured buffer; do not free memory
         * while any partially initialized USB task could still reference it. */
        return err;
    }
    /* The native PHY previously exposed Serial/JTAG. Give the host a clear
     * detach interval before announcing the UVC descriptors. Only at startup. */
    if (!tud_disconnect())
        return ESP_FAIL;
    vTaskDelay(pdMS_TO_TICKS(250));
    if (!tud_connect())
        return ESP_FAIL;
    ESP_LOGI(TAG, "USB UVC ready: HD 1280x720 MJPEG, up to %d FPS, bulk transfer", CONFIG_UVC_CAM1_FRAMERATE);
    return ESP_OK;
}
