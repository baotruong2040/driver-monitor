# Bước 5.1 — EAR liên tục cho model thứ hai

Gói cập nhật cho driver-monitor Windows đã có bước 2–5. Không cần cài thêm thư viện.
Giữ các tệp bước 2 và model hiện tại. `README-step05.md` giải thích phần cửa sổ cũ;
đọc tài liệu này cho phần bổ sung mới. Chưa train model, chưa phát âm thanh.

## Cài và kiểm tra

```powershell
Expand-Archive -Path "$env:USERPROFILE\Downloads\driver-monitor-step05-1.zip" -DestinationPath "$env:USERPROFILE\Documents\VSCode\AI" -Force
Set-Location "$env:USERPROFILE\Documents\VSCode\AI\driver-monitor"
.\.venv\Scripts\python.exe -m unittest -v test_behavior.py test_windows.py test_ear_windows.py
```

Dự kiến 53 tests, OK. Cấu trúc ZIP có sẵn thư mục driver-monitor, nên giải nén vào AI.

## Hiểu phép chuẩn hóa

Mỗi mắt có một baseline EAR mắt mở lấy từ hiệu chỉnh 8 giây:

`left_ear_norm = left_ear / left_ear_baseline`

`right_ear_norm = right_ear / right_ear_baseline`

Ví dụ baseline EAR .30, số đo .15 thì EAR chuẩn hóa .50.
Đây là 50% giá trị EAR baseline, KHÔNG phải kết luận mí mắt khép 50%.
Khoảng 1 nghĩa là EAR gần mức mắt mở lúc hiệu chỉnh. Giá trị có thể vượt 1,
vẫn giữ nguyên. Không tự ép vào [0,1] và không dùng trị thấp làm nhãn buồn ngủ.
EAR tóm tắt hình học độ mở mắt từ landmarks, chưa phải ảnh mắt hoặc toàn bộ hình
dạng mắt. Chuẩn hóa giúp so tương đối theo baseline, vẫn cần kiểm chứng khi khác
người, góc đầu, camera hoặc ánh sáng.

## Các cột mới trong windows CSV

| Cột | Ý nghĩa |
|---|---|
| left_ear_mean/std/p10, right_ear_mean/std/p10 | Thống kê EAR thô từng mắt |
| left_ear_norm_mean/std/p10, right_ear_norm_mean/std/p10 | Thống kê EAR chuẩn hóa từng mắt |
| bilateral_ear_norm_mean/std/p10 | Thống kê trung bình EAR chuẩn hóa hai mắt từng khoảng thời gian |
| ear_norm_absdiff_mean | Trung bình độ chênh tuyệt đối EAR chuẩn hóa hai mắt |
| ear_valid_s, ear_valid_ratio | Thời gian có EAR hợp lệ / tỷ lệ trên 30 giây |
| ear_norm_valid_s, ear_norm_valid_ratio | Thời gian có cả EAR và baseline hợp lệ / tỷ lệ trên 30 giây |
| ear_norm_usable | 1 nếu EAR chuẩn hóa có >= min-valid thời gian hợp lệ |
| model_input_usable | all_channels_usable AND ear_norm_usable |

`mean` là trung bình, `std` là độ lệch chuẩn, `p10` là phân vị 10% theo trọng số
thời gian. Tính thống kê theo giây, không theo số frame. Mỗi giá trị ở đầu khoảng
được giữ cho khoảng đến frame kế tiếp, chỉ khi hai frame đều có số đo hợp lệ,
frame kế tiếp không vượt window_end và gap <= .2 giây. p10 được lấy từ hàm phân
phối tích lũy trọng số, không nội suy. Phần đuôi chưa có hai đầu quan sát không
được cộng. Missing values giữ trống.

EAR liên tục và trạng thái mắt có chất lượng riêng. Khi hai EAR đo hợp lệ nhưng
trạng thái hai mắt bất đồng, eye_state có thể UNKNOWN; vẫn giữ EAR liên tục.
Nếu mất mặt, invalid geometry, EAR âm/NaN hoặc gap quá lớn, không tính khoảng đó.
Độ chênh EAR cao có thể do nháy một mắt, nheo mắt, góc đầu hoặc lỗi landmarks;
chưa tự gán ý nghĩa buồn ngủ. Geometry hợp lệ chưa bảo đảm quan sát hoàn hảo.

Giữ nguyên các đặc trưng cũ và quy tắc ngắt/cờ mắt từ bước 5. Các cột bổ sung
cho model thấy cả độ mở tương đối lẫn hành vi đóng/mở trong 30 giây.

## Xuất từ báo cáo bạn đã gửi, không cần chạy lại video

Tệp `_frames.csv` cũ có EAR nhưng chưa có baseline từng frame. Dùng JSON lần chạy
để lấy đúng baseline đã hoàn tất trước thời điểm đang xét:

```powershell
.\.venv\Scripts\python.exe check_windows.py --frames ".\reports\behavior_20261011_193409_915924_frames.csv" --events ".\reports\behavior_20261011_193409_915924_events.csv" --report ".\reports\behavior_20261011_193409_915924.json" --output ".\reports\behavior_20261011_193409_915924_step051_windows.csv"
```

--report là JSON LẦN CHẠY, không phải `_windows.json`. Ba tệp phải cùng một lần
chạy; mã kiểm tra tên frames/events trong JSON. Nhấn C hiệu chỉnh lại thì dùng
baseline đã hoàn tất gần nhất trước frame, không lấy baseline tương lai.
Baseline thay đổi giữa hai frame làm khoảng EAR chuẩn hóa đó không hợp lệ.
Nếu CSV cũ không có baseline và cũng không cung cấp report, vẫn xuất thống kê
EAR thô nhưng cột chuẩn hóa trống và model_input_usable=0. Không đoán baseline
bằng trung bình cả video hay EAR trong cửa sổ vì có thể chứa nhiều lần nhắm.

Không ghi đè tệp đầu ra. Nếu tên đã tồn tại, đặt --output tên khác.
`examples/behavior_20261011_193409_915924_step051_windows.csv` và JSON tương ứng
trong ZIP là kết quả đã tính từ chính ba tệp bạn gửi. Đây là bản xuất mới, không
thay thế báo cáo gốc.

## Chạy mới

```powershell
.\.venv\Scripts\python.exe check_behavior.py --camera 0 --seconds 120
.\.venv\Scripts\python.exe check_behavior.py --video ".\data\test.mp4"
```

Hiệu chỉnh 8 giây như trước. CSV frame mới lưu left_ear_baseline/right_ear_baseline;
sau khi dừng tự xuất windows schema_version=2, có đầy đủ cột EAR. --window 30,
--stride 5, --min-valid .8 và --pitch-sign dùng như trước. Model thật/Windows cần
bạn xác nhận tiếp. Không có vector cửa sổ hiển thị trực tiếp trong phiên bản này.

## Kết quả đã kiểm chứng

- 53 tests thành công, gồm tính theo thời gian, phân vị, chuẩn hóa từng mắt,
  không ép giá trị >1, thiếu baseline, bất đồng mắt, gap, hiệu chỉnh lại,
  không dùng baseline tương lai, kiểm tra report và Processor ghi baseline.
- Tái xuất đúng 17 cửa sổ của lần behavior_20261011_193409_915924; cả 17 có EAR
  chuẩn hóa. 11 dòng model_input_usable=1 và 6 dòng chưa đủ chất lượng.
- Tất cả giá trị đặc trưng cũ khớp với windows CSV bạn gửi.
- Ví dụ [8.048333,38.048333): bilateral normalized EAR mean ~.905, p10 ~.747.
  [33.048333,63.048333): mean ~.766, p10 ~.338, mắt nhắm và miệng mở trùng ~5.024s.
  Đây là số đo trên bài thử mô phỏng, không kết luận buồn ngủ.

## Trước khi train

Với baseline model dùng đủ các nhóm tín hiệu mới, lọc model_input_usable=1.
Giữ các dòng khác để phân tích lỗi, không tự điền label=awake. Gán subject_id,
video_id và label bằng nguồn nhãn thực. Chia theo người/video trước khi tạo cửa
sổ để không đưa các cửa sổ trùng frame vào hai tập. Các cột IDs, timestamps,
quality flags và label là quản lý/lọc dữ liệu, không tự đưa tất cả vào input.

Bước tiếp theo: xác định bộ dữ liệu và quy tắc gán nhãn thời gian cho trạng thái
buồn ngủ; sau đó train và đánh giá baseline trên người chưa có trong tập train.
