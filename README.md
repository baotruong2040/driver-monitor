# ESP32-S3 N16R8: USB UVC camera cho AI trên PC

Firmware ESP-IDF 6.0.1/PlatformIO đưa camera OV3660 thành webcam USB UVC/MJPEG.
Luồng hiện tại: camera → USB native → PC AI. Mã Wi-Fi/HTTP, viewer và test cũ
đã được dọn; firmware hiện tập trung vào USB, camera và IR/LDR.

## Cấu hình

- HD 1280×720, JPEG quality 10 trong source hiện tại, XCLK 20 MHz; UVC công bố 30 FPS.
  FPS thực tế cần đo ở PC, không suy ra chỉ từ descriptor.
  Khởi động kiểm tra bốn JPEG đầy đủ; nếu 20 MHz thất bại thì tự thử lại 16 MHz.
- Hai camera framebuffer PSRAM, CAMERA_GRAB_LATEST; bộ đệm UVC 256 KB.
  Driver sao chép JPEG rồi trả framebuffer ngay, không giữ camera khi truyền USB.
- UVC MJPEG bulk, một độ phân giải HD; không nén lại trên ESP32.
  Bộ đệm payload TinyUSB 1 KB, endpoint USB Full-Speed vẫn 64 byte đúng chuẩn.
  Cấu hình nằm trong lib/usb_camera_tusb_config.h, không sửa dependency quản lý.
  Thêm một byte đệm sau JPEG ở trường hợp gói cuối cần short packet để tách frame.
- TinyUSB ở core 0, camera UVC và driver camera ở core 1; tick FreeRTOS 1 ms.
- CPU 240 MHz, PSRAM Octal 8 MB/80 MHz, flash 16 MB.
- Giữ tự chuyển ngày/đêm và IR PWM 35% (358/1024), tần số 1 kHz.

Dependency: espressif/usb_device_uvc 1.3.1, TinyUSB 0.19.0~3, esp32-camera 2.1.8.
Khai báo trong src/idf_component.yml và khóa trong dependencies.lock.
src/CMakeLists.txt tránh biên dịch trùng descriptor giữa TinyUSB và UVC trong PlatformIO.

## Nhận ảnh trên Windows

Dùng cổng USB native nối GPIO19/20 (COM11 trước khi đổi firmware), dây có dữ liệu.
Khi app UVC chạy, Windows nhận camera; cổng USB Serial/JTAG COM11 có thể biến mất.
Sau RESET, firmware chờ 5 giây trước khi khởi tạo camera, rồi ngắt/kết nối USB
lại với khoảng nghỉ 250 ms. Chờ khoảng 7–10 giây để Windows nhận lại UVC CAM1.
Đóng Windows Camera/OBS/trình xem khác trước khi mở camera cho AI.

```powershell
ffmpeg -hide_banner -list_devices true -f dshow -i dummy
python diagnostics/usb_camera.py --seconds 15 --save .pio/usb-frame.png
python diagnostics/usb_camera.py --seconds 15 --ai-delay-ms 200
ffplay -f dshow -video_size 1280x720 -framerate 30 -use_video_device_timestamps false -framedrop -i "video=UVC CAM1"
```

Tên mặc định trên DirectShow: UVC CAM1 (sản phẩm USB: ESP32-S3 AI Camera).
Nếu Windows hiện tên khác, dùng --device "Tên camera".
Helper dùng FFmpeg trong PATH; lưu PNG cần Pillow, frame.bgr() cần NumPy.
USBCamera nhận liên tục trên thread riêng, chỉ giữ một ảnh mới nhất cho AI:

```python
import sys
sys.path.insert(0, "diagnostics")
from usb_camera import USBCamera

with USBCamera() as camera:
    sequence = 0
    while True:
        frame = camera.read_latest(sequence, timeout=5)
        if frame is None:
            continue
        sequence = frame.sequence
        image_bgr = frame.bgr()
        # result = model(image_bgr)
```

AI chậm sẽ bỏ ảnh chờ cũ, không ngăn thread nhận. received_at là thời điểm PC
nhận đủ ảnh, không phải timestamp chụp ở cảm biến. Có thể dùng OpenCV/DirectShow
để đọc thiết bị UVC, chọn đúng camera/MJPG/1280×720 và FPS đang được thiết bị công bố.
Helper tự đọc FPS từ DirectShow; có thể chọn rõ bằng --fps 30 sau khi nạp bản mới.

## Build, nạp và log

```powershell
pio run
pio run -t upload --upload-port COM11
python tests/startup_test.py
python tests/camera_clock_test.py
```

Sau khi app đổi USB sang UVC, để nạp lại bằng cổng native: giữ BOOT, nhấn rồi
thả RESET, thả BOOT; tìm lại COM bằng pio device list rồi nạp. Không thay đổi eFuse.
PlatformIO dùng watchdog_reset sau khi nạp để thoát chế độ download của USB native.
Nếu board có cổng UART riêng, dùng cổng đó để nạp và đọc log.

Log LDR mỗi giây và UVC capture mỗi 5 giây vẫn có trên UART0, 115200 baud.
Log không đi vào video USB.

## LDR và IR-CUT

- GPIO2/ADC1, đọc mỗi 100 ms; raw ≤300 liên tục 5 giây chuyển NIGHT, bật IR 35%.
- Raw ≥2300 liên tục 15 giây chuyển DAY, tắt IR; ở giữa giữ chế độ hiện tại.
- GPIO42/41 điều khiển IR-CUT với xung 200 ms. GPIO40/39 điều khiển IR.
- PWM điều chỉnh tải trung bình, không thay thế mạch hạn dòng LED IR.

## Cấu trúc dự án

- `src/main.c`, `lib/`: firmware camera USB, IR/LDR.
- `src/cam.py`: mã AI nhận diện mắt/buồn ngủ của bạn, được giữ nguyên.
- `diagnostics/usb_camera.py`: chương trình PC nhận ảnh USB mới nhất cho AI.
- `tests/`: kiểm tra khởi động, fallback clock và ranh giới payload USB.
- `backups/usb_uvc_hd_stable_2026-10-06/`: một bộ khôi phục source và firmware
  của bản HD khoảng 17,4 FPS đã kiểm tra. Xem `RESTORE.md` trong thư mục đó.
- `managed_components/`, `.pio/build/`: dependency và cache build do công cụ
  quản lý; giữ để không phải tải/biên dịch lại toàn bộ SDK.

Kết quả mới nhất: [XCLK 20 MHz và sửa payload USB](diagnostics/camera_clock20_2026-10-06.md).
Lượt đo HD/JPEG 20 trước đó đạt khoảng 17,43 FPS, không có lỗi giải mã trong
hai lượt đo bình thường và AI mô phỏng chậm. Bản JPEG 15 mới đã được kiểm tra:
HD nhận khoảng 17,45 FPS, không có lỗi giải mã trong lượt đo 30 giây.
[Kết quả JPEG 15](diagnostics/jpeg_quality15_2026-10-06.md). Giữ IR 35% và CPU 240 MHz.
