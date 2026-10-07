# Tăng chất lượng JPEG, giữ HD

Source chuyển JPEG quality từ 18 xuống 15; với OV3660, số nhỏ hơn là nén nhẹ
hơn/chất lượng cao hơn. Giữ HD 1280×720, XCLK 20 MHz (fallback 16 MHz), CPU
240 MHz, IR 35% và giao thức USB UVC hiện tại. Không chuyển sang Full HD.

Build và kiểm tra startup/fallback đều qua. Người dùng đã nạp; lượt này chỉ
kiểm tra luồng USB, không ghi flash. Ban đầu COM11 biến mất trước lúc verify_flash
mở cổng, nên không có kết quả đối chiếu digest trong lượt này. Sau đó Windows
nhận UVC CAM1 và video chạy thành công.

## Kết quả nhận USB trong khoảng 30 giây

- Độ phân giải: 1280×720.
- 515 ảnh nhận, 513 ảnh phía xử lý lấy.
- FPS thực nhận: 17,45; chế độ UVC yêu cầu 30 FPS.
- Không có dòng lỗi giải mã JPEG trong log FFmpeg.
- Khoảng frame dài nhất: 79,8 ms.
- Ảnh PNG đã kiểm tra trực quan; JPEG gốc đã giải mã bằng Pillow.
- JPEG mẫu: 30.154 byte, hệ số lượng tử luma đầu tiên 15, chroma đầu tiên 16;
  dữ liệu JPEG gốc xác nhận mức lượng tử mới. Đây không phải cỡ ảnh trung bình.

So với lượt HD/JPEG 20 trước (~17,43 FPS), chưa thấy giảm FPS rõ rệt. Các lượt
khác thời điểm/cảnh nên không coi là so sánh chất lượng hoặc băng thông A/B
kiểm soát. Chưa đo độ trễ glass-to-glass hoặc chạy model AI thật trong lượt này.

Bản khôi phục HD đã đo trước đó còn trong backups/usb_uvc_hd_stable_2026-10-06/.
