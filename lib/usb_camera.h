#pragma once

#include "esp_err.h"

/* Expose the initialized JPEG camera as a standard USB UVC webcam. */
esp_err_t usb_camera_start(void);
