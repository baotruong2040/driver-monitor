# Thử XCLK 20 MHz, giữ HD và chất lượng JPEG

## Thay đổi

- XCLK camera thử 20 MHz trước, sử dụng profile JPEG PLL mặc định của driver
  OV3660. Theo hàm tính clock của driver: 16 MHz dùng SYSCLK 32 MHz/PCLK 8 MHz;
  20 MHz dùng SYSCLK 50 MHz/PCLK 10 MHz.
- OV3660 có dải input clock 6–27 MHz theo [datasheet](https://files.seeedstudio.com/wiki/SeeedStudio-XIAO-ESP32S3/res/OV3660_datasheet.pdf).
  Bản này dùng clock trong dải đó, không chỉnh điện áp, CPU hoặc duty IR.
- Giữ 1280×720, JPEG quality 20, IR 35%, CPU 240 MHz, UVC bulk payload 1 KB.
- Kiểm tra JPEG SOI/EOI và kích thước bốn frame lúc khởi động. Nếu cấu hình
  20 MHz lỗi, deinit camera rồi thử lại 16 MHz; camera lỗi không được đưa vào
  chế độ nhận ảnh USB.
- Helper PC dùng timestamp host thay vì timestamp thiết bị: tránh đồng hồ
  DirectShow chạy theo FPS khai báo khi FPS thực tế thấp hơn.

## Kiểm tra đã thực hiện

- PlatformIO build và nạp COM11 thành công; hash flash được xác nhận khi nạp.
- Test host xác nhận 20 MHz hợp lệ không fallback; timeout hoặc JPEG hỏng
  tại 20 MHz sẽ thử 16 MHz, trả framebuffer và deinit đúng thứ tự; cả hai
  profile lỗi thì camera vẫn chưa sẵn sàng.
- Startup test và kiểm tra cú pháp helper PC đều qua.
- Board đã trở lại UVC và được kiểm tra trên Windows/DirectShow.

## Sửa kết thúc payload USB

Lượt 20 MHz đầu đạt 17,05 FPS nhưng có 10 dòng lỗi giải mã trong 30 giây.
TinyUSB 0.19 không thêm zero-length packet khi payload cuối ngắn hơn giới hạn
1 KB nhưng kết thúc đúng bội số endpoint 64 byte. Khi đó host có thể nhập
ranh giới payload kế tiếp vào payload trước.

usb_video_limits.h thêm đúng một byte đệm sau JPEG EOI ở trường hợp này.
Framebuffer đã lấy có dung lượng 256 KB; kiểm tra giới hạn trước khi ghi byte
đệm và giữ nguyên len của ảnh camera gốc. Các frame còn lại không thêm byte.
Kiểm tra tất cả độ dài 4..262144 xác nhận transfer cuối có ranh giới hợp lệ.
Pillow xác nhận JPEG thử ở trường hợp biên giải mã ra pixel HD giống hệt trước
và sau đệm. Clock, điện áp, CPU, IR và chất lượng JPEG không đổi ở bước sửa này.

## Kết quả bản cuối đã nạp

| Chỉ số | Nhận bình thường (~30 s) | AI mô phỏng 200 ms/ảnh (~15 s) |
|---|---:|---:|
| Ảnh nhận | 519 | 255 |
| Ảnh phía xử lý lấy | 516 | 73 |
| Ảnh chờ cũ bỏ để ưu tiên ảnh mới | 0 | 179 |
| FPS thực nhận | 17,43 | 17,42 |
| Dòng lỗi giải mã | 0 | 0 |
| Khoảng ảnh dài nhất (ms) | 87,5 | 74,4 |

Ảnh kiểm tra có kích thước 1280×720 và đã được kiểm tra trực quan; ảnh/log
tạm thời được dọn sau khi ghi lại kết quả.
So với 11,16 FPS ở 16 MHz, tốc độ tăng khoảng 56%. Thiết bị vẫn công bố 30 FPS;
17,4 FPS là kết quả nhận/giải mã thực tế, không nội suy hoặc nhân đôi ảnh.
Ảnh mới tiếp tục được nhận khi AI chậm, hàng đợi chỉ giữ một ảnh mới nhất.

Camera startup/fallback test và USB payload test đều qua, bản sửa cuối build
và nạp thành công. Sau nạp đã dùng reset watchdog chuẩn esptool để thoát chế
độ download. Chưa đo nhiệt độ trực tiếp hoặc độ trễ glass-to-glass; các test
phần mềm không xác nhận nhiệt độ. Không tăng thêm clock vượt cấu hình mặc định
20 MHz đã chọn, không đổi điện áp/CPU/IR/eFuse.

Bộ khôi phục còn giữ sau khi dọn dự án: backups/usb_uvc_hd_stable_2026-10-06/,
có source và firmware của bản cuối HD khoảng 17,4 FPS.
