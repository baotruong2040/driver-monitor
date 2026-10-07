#include <assert.h>
#include <stdio.h>
#include "usb_video_limits.h"

int main(void)
{
    unsigned padded = 0;
    for (size_t length = 4; length <= 256u * 1024u; length++) {
        size_t result = usb_video_frame_length(length);
        assert(result == length || result == length + 1);
        assert(result <= 256u * 1024u);
        size_t tail = result % (USB_VIDEO_PAYLOAD_BYTES - USB_VIDEO_HEADER_BYTES);
        /* A full maximum payload is delimited by its negotiated length;
         * every shorter payload must end with a short physical USB packet. */
        assert(tail == 0 || (tail + USB_VIDEO_HEADER_BYTES) % USB_VIDEO_PACKET_BYTES != 0);
        if (result != length) {
            size_t original_tail = length % (USB_VIDEO_PAYLOAD_BYTES - USB_VIDEO_HEADER_BYTES);
            assert(original_tail && (original_tail + USB_VIDEO_HEADER_BYTES) % USB_VIDEO_PACKET_BYTES == 0);
            padded++;
        }
    }
    assert(usb_video_frame_length(62) == 63);
    assert(usb_video_frame_length(1022) == 1022);
    assert(usb_video_frame_length(1084) == 1085);
    assert(padded > 0);
    printf("USB payload: all JPEG lengths 4..262144 have a valid transfer boundary (%u padded)\n", padded);
}
