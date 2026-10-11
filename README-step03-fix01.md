# Bước 3 — sửa chuyển tiếp không đồng thời giữa hai mắt

## Lỗi được phát hiện từ lần chạy 20261011_174638_645287

Camera và model chạy ổn: khoảng 29,01 FPS, không có frame gap trên 200 ms.
Tuy nhiên logic cũ ngắt ngay một sự kiện khi hai mắt có trạng thái khác nhau.
Khi mở lại sau nhắm, một mắt có thể vượt ngưỡng trước mắt kia một frame.
Đó có thể chỉ là lệch ngưỡng/landmarks, không phải mất quan sát.

Ví dụ từ frame CSV:

- 15,623339 s: hai mắt vẫn CLOSED.
- 15,655583 s: EAR trái 0,221887 chưa đạt ngưỡng mở 0,223737; EAR phải 0,248255 đã vượt ngưỡng mở 0,247799.
- 15,687588 s: hai mắt đều vượt ngưỡng mở.

Mã cũ đã ngắt ở frame giữa và bỏ sự kiện. Đó là vấn đề máy trạng thái,
không cần thay ngưỡng EAR hoặc cài lại MediaPipe để sửa.

## Thay đổi

- Giữ trạng thái hysteresis riêng của từng mắt trong chuyển tiếp hợp lệ.
- Cho phép bất đồng ngắn tối đa 0,12 giây khi cả hai mắt vẫn có EAR hợp lệ.
- Trạng thái chung trong khoảng này vẫn UNKNOWN. Không tạo cờ nhắm lâu tại frame UNKNOWN.
- Nếu hai mắt cùng OPEN trong khoảng cho phép, hoàn tất sự kiện tại frame đầu một mắt mở.
- Nếu quay lại cùng CLOSED trong khoảng cho phép, tiếp tục sự kiện; đây là quy tắc chịu nhiễu cần kiểm chứng bằng dữ liệu thực.
- Nếu bất đồng kéo dài quá 0,12 giây, ngắt sự kiện đến frame cuối cả hai mắt CLOSED.
- Khi hai mắt đóng lệch nhau ngắn, chỉ bắt đầu sự kiện tại frame cả hai CLOSED và trước đó đã quan sát OPEN.
- NO_FACE, vùng mắt không hợp lệ và gián đoạn frame > 0,20 giây vẫn ngắt ngay.
- Lấy lại mặt với mắt đã nhắm vẫn không đoán mốc bắt đầu và không ghép với sự kiện trước che mặt.

0,12 giây là tham số thử nghiệm để xử lý chuyển tiếp, không phải ngưỡng sinh lý.
Quy tắc này có thể nối một dao động EAR ngắn; cần so với thao tác thật hoặc
video có nhãn để đánh giá đúng/sai. Nếu đổi FPS hoặc dùng camera khác, kiểm tra lại.

Tài liệu này cập nhật phần xử lý hai mắt bất đồng trong README-step03.md cũ.
Các quy tắc thiếu quan sát, hiệu chỉnh và phân loại thời lượng giữ như trước.

## Cài bản sửa trong PowerShell

ZIP chỉ thay eye_events.py và test_eye_events.py, thêm bài giải thích này.
Nó dùng check_eyes.py, model và .venv đã có; không có dependency mới.
Đóng chương trình check_eyes.py trước khi giải nén.

```powershell
Expand-Archive -Path "$env:USERPROFILE\Downloads\driver-monitor-step03-fix01.zip" -DestinationPath "$env:USERPROFILE\Documents\VSCode\AI" -Force
Set-Location "$env:USERPROFILE\Documents\VSCode\AI\driver-monitor"
.\.venv\Scripts\python.exe -m unittest -v test_eye_events.py
```

Kết quả dự kiến: Ran 20 tests và OK.

```powershell
.\.venv\Scripts\python.exe check_eyes.py --camera 0 --seconds 60
```

8 giây hiệu chỉnh đầu: nhìn thẳng, giữ mắt mở tự nhiên.
Sau hiệu chỉnh:

1. Chớp nhanh có chủ đích 5 lần, cách nhau khoảng 2 giây. Không giữ mắt đóng lâu; một sự kiện trên 0,50 giây được ghi prolonged_closure theo cấu hình hiện tại.
2. Nhắm khoảng 2 giây rồi mở: kiểm tra LONG CLOSURE và completed prolonged closure.
3. Che mặt khoảng 3 giây: kiểm tra UNKNOWN và không cộng thời gian che.
4. Mở mắt, chớp thêm 2 lần: kiểm tra phục hồi.

Gửi JSON và hai CSV mới, kèm số lần chớp chủ đích và nhận xét trạng thái.
Chưa cần chỉnh close-ratio/open-ratio trong lần thử này.

## Kiểm tra đã thực hiện

20 bài kiểm tra logic đã qua, gồm hồi quy theo frame EAR thực của báo cáo,
hai mắt mở/đóng lệch frame, bất đồng dài, mất mặt trong chuyển tiếp,
nhắm lâu, frame gap và lấy lại mặt với mắt đang nhắm.

Phát lại chuỗi EAR của lần chạy bạn gửi bằng mã mới, giữ nguyên ngưỡng:

| Loại bản ghi | Mã cũ | Phát lại bằng mã sửa |
| --- | ---: | ---: |
| blink_candidate | 0 | 6 |
| prolonged_closure hoàn tất | 1 | 9 |
| interrupted_closure | 17 | 6 |
| long_closure_flag | 1 | 1 |

Hai lần ngắt do NO_FACE vẫn giữ nguyên mốc: 57,207602–57,779382 s
và 64,343743–65,671366 s. Khoảng mất mặt không được cộng vào hai sự kiện này.

Đây là kết quả tính lại từ EAR đã ghi, không phải lần chạy webcam mới,
không phải xác nhận bạn chớp đúng 6 lần và không phải phép đo độ chính xác.
Cờ long_closure và bản ghi prolonged_closure có thể thuộc cùng một sự kiện.
