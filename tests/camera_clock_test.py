"""Check clock fallback and frame ownership using the real camera wrapper."""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
build = root / ".pio" / "host-tests"
build.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(dir=build) as temporary:
    directory = Path(temporary)
    headers = {
        "esp_err.h": """#pragma once
typedef int esp_err_t;
#define ESP_OK 0
#define ESP_FAIL -1
#define ESP_ERR_NO_MEM -2
#define ESP_ERR_TIMEOUT -3
static inline const char *esp_err_to_name(int e) { (void)e; return "test"; }
""",
        "esp_log.h": """#pragma once
#define ESP_LOGI(tag, ...) ((void)(tag))
#define ESP_LOGE(tag, ...) ((void)(tag))
#define ESP_LOGW(tag, ...) ((void)(tag))
""",
        "esp_heap_caps.h": """#pragma once
#include <stddef.h>
#define MALLOC_CAP_SPIRAM 1
static inline size_t heap_caps_get_free_size(int c) { (void)c; return 8000000; }
static inline size_t heap_caps_get_total_size(int c) { (void)c; return 8000000; }
""",
        "esp_camera.h": """#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"
enum { LEDC_TIMER_0, LEDC_CHANNEL_0, PIXFORMAT_JPEG, FRAMESIZE_HD,
       CAMERA_FB_IN_PSRAM, CAMERA_GRAB_LATEST };
typedef struct {
    int pin_pwdn, pin_reset, pin_xclk, pin_sccb_sda, pin_sccb_scl;
    int pin_d0, pin_d1, pin_d2, pin_d3, pin_d4, pin_d5, pin_d6, pin_d7;
    int pin_vsync, pin_href, pin_pclk;
    uint32_t xclk_freq_hz;
    int ledc_timer, ledc_channel, pixel_format, frame_size, jpeg_quality;
    size_t jpeg_buffer_size;
    int fb_count, fb_location, grab_mode;
} camera_config_t;
typedef struct { uint8_t *buf; size_t len, width, height; int format; } camera_fb_t;
typedef struct sensor sensor_t;
struct sensor {
    struct { unsigned PID; } id;
    int (*set_pixformat)(sensor_t *, int);
    int (*set_framesize)(sensor_t *, int);
    int (*set_quality)(sensor_t *, int);
    int (*set_brightness)(sensor_t *, int);
    int (*set_contrast)(sensor_t *, int);
    int (*set_saturation)(sensor_t *, int);
    int (*set_whitebal)(sensor_t *, int);
    int (*set_awb_gain)(sensor_t *, int);
    int (*set_exposure_ctrl)(sensor_t *, int);
    int (*set_gain_ctrl)(sensor_t *, int);
};
typedef struct { unsigned width, height; } resolution_t;
extern const resolution_t resolution[8];
esp_err_t esp_camera_init(const camera_config_t *config);
esp_err_t esp_camera_deinit(void);
sensor_t *esp_camera_sensor_get(void);
camera_fb_t *esp_camera_fb_get(void);
void esp_camera_fb_return(camera_fb_t *frame);
bool esp_camera_get_psram_mode(void);
""",
    }
    for name, content in headers.items():
        (directory / name).write_text(content, encoding="utf-8")
    harness = r'''
#include <assert.h>
#include <stdio.h>
#include "camera.h"
const resolution_t resolution[8] = {[FRAMESIZE_HD] = {1280, 720}};
static unsigned clock_hz, calls, deinit_calls, returned;
static bool active, outstanding;
static int failure_mode;
static int first_quality;
static uint8_t jpeg[] = {255,216,255,224,255,217};
static camera_fb_t frame = {.buf=jpeg, .len=sizeof(jpeg),
                           .width=1280, .height=720, .format=PIXFORMAT_JPEG};
static int set(sensor_t *sensor, int value) { (void)sensor; (void)value; return 0; }
static sensor_t sensor = {.id={0x3660}, .set_pixformat=set, .set_framesize=set,
    .set_quality=set, .set_brightness=set, .set_contrast=set, .set_saturation=set,
    .set_whitebal=set, .set_awb_gain=set, .set_exposure_ctrl=set, .set_gain_ctrl=set};
esp_err_t esp_camera_init(const camera_config_t *config) {
    assert(!active && !outstanding);
    assert(config->frame_size == FRAMESIZE_HD);
    assert(config->jpeg_quality >= 0 && config->jpeg_quality <= 63);
    clock_hz = config->xclk_freq_hz;
    if (calls++ == 0) {
        assert(clock_hz == 20000000);
        first_quality = config->jpeg_quality;
    } else {
        assert(clock_hz == 16000000 && config->jpeg_quality == first_quality);
    }
    active = true;
    return ESP_OK;
}
esp_err_t esp_camera_deinit(void) {
    assert(active && !outstanding);
    active = false; deinit_calls++; return ESP_OK;
}
sensor_t *esp_camera_sensor_get(void) { assert(active); return &sensor; }
camera_fb_t *esp_camera_fb_get(void) {
    assert(active && !outstanding);
    if (failure_mode == 1 && clock_hz == 20000000) return NULL;
    jpeg[5] = ((failure_mode == 2 && clock_hz == 20000000) || failure_mode == 3) ? 0 : 217;
    outstanding = true;
    return &frame;
}
void esp_camera_fb_return(camera_fb_t *value) {
    assert(value == &frame && outstanding);
    outstanding = false; returned++;
}
bool esp_camera_get_psram_mode(void) { return false; }
static void reset(int mode) {
    calls = deinit_calls = returned = 0; active = outstanding = false;
    failure_mode = mode;
}
int main(void) {
    reset(0);
    assert(camera_init() == ESP_OK && camera_is_ready());
    assert(calls == 1 && deinit_calls == 0 && returned == 4);
    esp_camera_deinit();
    reset(1);
    assert(camera_init() == ESP_OK && camera_is_ready());
    assert(calls == 2 && deinit_calls == 1 && returned == 4);
    esp_camera_deinit();
    reset(2);
    assert(camera_init() == ESP_OK && camera_is_ready());
    assert(calls == 2 && deinit_calls == 1 && returned == 5);
    esp_camera_deinit();
    reset(3);
    assert(camera_init() != ESP_OK && !camera_is_ready());
    assert(calls == 2 && deinit_calls == 2 && returned == 2 && !active);
    puts("Camera clock: valid 20 MHz; fallback after timeout/corrupt JPEG; failed camera stays unavailable");
}
'''
    source = directory / "camera_clock_test.c"
    source.write_text(harness, encoding="utf-8")
    executable = directory / "camera_clock_test.exe"
    subprocess.run([shutil.which("gcc"), "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-I", str(directory), "-I", str(root / "lib"),
                    str(root / "lib/camera.c"), str(source), "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
