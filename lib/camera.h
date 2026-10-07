#ifndef CAMERA_H
#define CAMERA_H

#include <stdbool.h>
#include "esp_err.h"
#include "esp_camera.h"

#define CAMERA_JPEG_BUFFER_SIZE (256u * 1024u)

/* SCCB */
#define CAM_PIN_SIOD       4
#define CAM_PIN_SIOC       5

/* SYNC */
#define CAM_PIN_VSYNC      6
#define CAM_PIN_HREF       7
#define CAM_PIN_PCLK       13

/* CLOCK */
#define CAM_PIN_XCLK       15

#define CAM_PIN_Y2         11
#define CAM_PIN_Y3         9
#define CAM_PIN_Y4         8
#define CAM_PIN_Y5         10
#define CAM_PIN_Y6         12
#define CAM_PIN_Y7         18
#define CAM_PIN_Y8         17
#define CAM_PIN_Y9         16

#define CAM_PIN_PWDN       -1
#define CAM_PIN_RESET      -1

esp_err_t camera_init(void);
bool camera_is_ready(void);

camera_fb_t *camera_get_frame(void);
void camera_return_frame(camera_fb_t *fb);

#endif
