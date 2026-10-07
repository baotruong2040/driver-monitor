#pragma once

#include "tusb_config.h"
#include "usb_video_limits.h"

/* Full-speed bulk endpoints still advertise 64-byte USB packets. A UVC payload
 * may span several packets: aggregate them in a larger transfer buffer instead
 * of requiring a TinyUSB task round trip for each 64-byte payload. */
#if CFG_TUD_CAM1_VIDEO_STREAMING_BULK
#undef CFG_TUD_VIDEO_STREAMING_EP_BUFSIZE
#define CFG_TUD_VIDEO_STREAMING_EP_BUFSIZE USB_VIDEO_PAYLOAD_BYTES
#endif
