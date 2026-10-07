#pragma once

#include <stddef.h>

#define USB_VIDEO_PAYLOAD_BYTES 1024u
#define USB_VIDEO_PACKET_BYTES 64u
#define USB_VIDEO_HEADER_BYTES 2u

/* TinyUSB UVC does not append a ZLP for a short logical payload ending on a
 * full USB packet. One trailing JPEG padding byte makes that transfer end in
 * a short packet, so the host cannot combine it with the next frame header. */
static inline size_t usb_video_frame_length(size_t jpeg_length)
{
    size_t tail = jpeg_length % (USB_VIDEO_PAYLOAD_BYTES - USB_VIDEO_HEADER_BYTES);
    return jpeg_length + (tail != 0 && (tail + USB_VIDEO_HEADER_BYTES) % USB_VIDEO_PACKET_BYTES == 0);
}
