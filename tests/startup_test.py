"""Check USB starts only after successful camera initialization."""
from pathlib import Path
import shutil
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
compiler = shutil.which("gcc") or r"C:\msys64\mingw64\bin\gcc.exe"
build_root = root / ".pio" / "host-tests"
build_root.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(dir=build_root) as directory:
    directory = Path(directory)
    (directory / "freertos").mkdir()
    (directory / "freertos/FreeRTOS.h").write_text(
        "#define pdMS_TO_TICKS(ms) (ms)\n", encoding="utf-8"
    )
    (directory / "freertos/task.h").write_text(
        "static inline void vTaskDelay(unsigned ticks) { (void)ticks; }\n", encoding="utf-8"
    )
    (directory / "esp_err.h").write_text(
        "#pragma once\ntypedef int esp_err_t;\n#define ESP_OK 0\n", encoding="utf-8"
    )
    declarations = {
        "camera.h": "esp_err_t camera_init(void);",
        "drv8833.h": "esp_err_t drv8833_init(void); void drv8833_set_day(void);",
        "ldr.h": "esp_err_t ldr_start(void);",
        "usb_camera.h": "esp_err_t usb_camera_start(void);",
    }
    for name, declaration in declarations.items():
        (directory / name).write_text(
            '#include "esp_err.h"\n' + declaration, encoding="utf-8"
        )
    (directory / "esp_log.h").write_text(
        "#define ESP_LOGE(...) ((void)0)\n#define ESP_LOGI(...) ((void)0)\n", encoding="utf-8"
    )
    harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
void app_main(void);
static char calls[16];
static unsigned count;
static int drv_result, ldr_result, usb_result, camera_result;
static bool camera_ready, usb_up;
static void call(char value) { calls[count++] = value; calls[count] = 0; }
int drv8833_init(void) { call('D'); return drv_result; }
void drv8833_set_day(void) { call('d'); }
int ldr_start(void) { call('L'); return ldr_result; }
int camera_init(void) {
    call('C'); camera_ready = camera_result == 0; return camera_result;
}
int usb_camera_start(void) {
    assert(camera_ready);
    call('U'); usb_up = usb_result == 0; return usb_result;
}
static void reset(void) {
    count = 0; calls[0] = 0; camera_ready = usb_up = false;
    drv_result = ldr_result = usb_result = camera_result = 0;
}
int main(void) {
    reset(); app_main(); assert(strcmp(calls, "DdLCU") == 0 && usb_up);
    reset(); camera_result = -1; app_main(); assert(strcmp(calls, "DdLC") == 0 && !usb_up);
    reset(); ldr_result = -1; app_main(); assert(usb_up);
    reset(); usb_result = -1; app_main(); assert(strcmp(calls, "DdLCU") == 0 && !usb_up);
    reset(); drv_result = -1; app_main(); assert(strcmp(calls, "D") == 0 && !usb_up);
    puts("Startup: USB follows valid camera; camera failure prevents USB capture");
    return 0;
}
'''
    source = directory / "startup_test.c"
    executable = directory / "startup_test.exe"
    source.write_text(harness, encoding="utf-8")
    subprocess.run(
        [compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
         "-I", str(directory), str(root / "src/main.c"), str(source),
         "-o", str(executable)], check=True,
    )
    subprocess.run([str(executable)], check=True)
